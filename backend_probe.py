"""Backend selection probe helpers.

This module intentionally keeps two layers separate:

1. Pure selection logic (`select_backend`, `get_probe_order`, cache helpers)
2. Real backend probes (`probe_gguf_backend`, `probe_pytorch_backend`)

PR 1 landed layer 1 with mocked tests. PR 2 adds layer 2 but still does not
wire anything into app bootstrap yet.

macOS currently returns a single-candidate probe order (`["pytorch"]`) on
purpose. GGUF Metal stays out of v1 until real hardware validation exists.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping


BackendName = Literal["gguf", "pytorch"]
ProbeFn = Callable[[BackendName], "ProbeOutcome"]

USE_GGUF_ENV = "USE_GGUF_BACKEND"
USE_PYTORCH_ENV = "USE_PYTORCH_BACKEND"
PROBE_TEXT = "你好。"
PROBE_VOICE_ID = "uncle_fu"
MODEL_DEFAULT = "Qwen3-TTS-12Hz-1.7B-CustomVoice"


class BackendProbeError(RuntimeError):
    """Raised when no backend can be selected via probe."""


class BackendOverrideConflictError(RuntimeError):
    """Raised when both backend override env vars are enabled."""


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    gpu_vendor: str
    gpu_device_identity: str
    has_cuda: bool = False
    has_vulkan: bool = False
    has_dml: bool = False
    has_mps: bool = False
    has_rocm: bool = False
    vram_gb: float | None = None

    @property
    def normalized_os(self) -> str:
        value = self.os_name.strip().lower()
        if value in {"win32", "windows"}:
            return "windows"
        if value in {"darwin", "mac", "macos"}:
            return "macos"
        if value.startswith("linux"):
            return "linux"
        return value

    @property
    def normalized_vendor(self) -> str:
        return self.gpu_vendor.strip().lower()

    @property
    def vram_bucket(self) -> str:
        if self.vram_gb is None:
            return "unknown"
        if self.vram_gb < 4:
            return "<4GB"
        if self.vram_gb < 8:
            return "4-8GB"
        if self.vram_gb < 12:
            return "8-12GB"
        return ">=12GB"


@dataclass(frozen=True)
class VersionProfile:
    torch_version: str = "unknown"
    qwen3_tts_gguf_version: str = "unknown"
    onnxruntime_version: str = "unknown"


@dataclass(frozen=True)
class ProbeOutcome:
    success: bool
    reason: str


@dataclass(frozen=True)
class BackendSelection:
    backend: BackendName
    reason: str
    source: Literal["override", "cache", "probe"]
    attempted_backends: tuple[BackendName, ...] = ()
    cache_key: dict[str, str] | None = None


@dataclass(frozen=True)
class ProbeCacheRecord:
    cache_key: dict[str, str]
    selected_backend: BackendName
    reason: str
    updated_at: str


@dataclass(frozen=True)
class SelectionResult:
    selection: BackendSelection
    cache_record: ProbeCacheRecord | None = None
    probe_log: tuple[str, ...] = field(default_factory=tuple)


def build_cache_key(hardware: HardwareProfile, versions: VersionProfile) -> dict[str, str]:
    return {
        "os": hardware.normalized_os,
        "gpu_vendor": hardware.normalized_vendor,
        "gpu_device_identity": hardware.gpu_device_identity.strip() or "unknown",
        "vram_bucket": hardware.vram_bucket,
        "torch_version": versions.torch_version,
        "qwen3_tts_gguf_version": versions.qwen3_tts_gguf_version,
        "onnxruntime_version": versions.onnxruntime_version,
        "model_default": MODEL_DEFAULT,
    }


def get_probe_cache_path(
    os_name: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = env or os.environ
    normalized_os = HardwareProfile(
        os_name=os_name or os.name,
        gpu_vendor="unknown",
        gpu_device_identity="unknown",
    ).normalized_os
    home = home or Path.home()

    if normalized_os == "windows":
        local_app_data = env.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "bashi-privacy-app" / "backend_probe.json"
        return home / "AppData" / "Local" / "bashi-privacy-app" / "backend_probe.json"

    if normalized_os == "macos":
        return home / "Library" / "Caches" / "bashi-privacy-app" / "backend_probe.json"

    xdg_cache_home = env.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "bashi-privacy-app" / "backend_probe.json"
    return home / ".cache" / "bashi-privacy-app" / "backend_probe.json"


def load_probe_cache(path: Path) -> ProbeCacheRecord | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProbeCacheRecord(
            cache_key=dict(data["cache_key"]),
            selected_backend=data["selected_backend"],
            reason=data["reason"],
            updated_at=data["updated_at"],
        )
    except Exception:
        return None


def write_probe_cache(path: Path, record: ProbeCacheRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_backend_env(selection: BackendSelection, env: dict[str, str] | None = None) -> None:
    env = env if env is not None else os.environ
    if selection.backend == "gguf":
        env[USE_GGUF_ENV] = "1"
        env.pop(USE_PYTORCH_ENV, None)
        return

    env[USE_PYTORCH_ENV] = "1"
    env.pop(USE_GGUF_ENV, None)


def check_env_override(env: Mapping[str, str] | None = None) -> BackendSelection | None:
    env = env or os.environ
    gguf = env.get(USE_GGUF_ENV)
    pytorch = env.get(USE_PYTORCH_ENV)

    if gguf == "1" and pytorch == "1":
        raise BackendOverrideConflictError(
            f"Conflicting backend overrides: {USE_GGUF_ENV}={gguf}, {USE_PYTORCH_ENV}={pytorch}. "
            "Unset one of them before starting the app."
        )

    if gguf == "1":
        return BackendSelection(
            backend="gguf",
            reason=f"{USE_GGUF_ENV}=1 override",
            source="override",
        )

    if pytorch == "1":
        return BackendSelection(
            backend="pytorch",
            reason=f"{USE_PYTORCH_ENV}=1 override",
            source="override",
        )

    return None


def get_probe_order(hardware: HardwareProfile) -> list[BackendName]:
    """Return primary-to-fallback probe order for the current platform."""
    os_name = hardware.normalized_os
    vendor = hardware.normalized_vendor

    if vendor == "nvidia" and hardware.has_cuda:
        return ["pytorch", "gguf"]

    if os_name == "windows" and vendor in {"amd", "intel"} and hardware.has_vulkan and hardware.has_dml:
        return ["gguf", "pytorch"]

    if os_name == "linux" and vendor == "amd" and hardware.has_rocm:
        return ["pytorch", "gguf"]

    if os_name == "linux" and vendor == "intel" and hardware.has_vulkan:
        return ["gguf", "pytorch"]

    if os_name == "macos" and hardware.has_mps:
        return ["pytorch"]

    return ["pytorch"]


def _safe_package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"
    except Exception:
        return "unknown"


def detect_version_profile() -> VersionProfile:
    return VersionProfile(
        torch_version=_safe_package_version("torch"),
        qwen3_tts_gguf_version=_safe_package_version("qwen3-tts-gguf"),
        onnxruntime_version=_safe_package_version("onnxruntime-directml")
        if _safe_package_version("onnxruntime-directml") != "not-installed"
        else _safe_package_version("onnxruntime"),
    )


def _detect_windows_gpu_name() -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return "unknown"

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if lines else "unknown"


def _detect_linux_gpu_name() -> str:
    try:
        result = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return "unknown"

    for line in result.stdout.splitlines():
        lower = line.lower()
        if "vga" in lower or "3d controller" in lower:
            return line.strip()
    return "unknown"


def _detect_macos_gpu_name() -> str:
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except Exception:
        return "unknown"

    for line in result.stdout.splitlines():
        if "Chipset Model:" in line:
            return line.split(":", 1)[1].strip()
    return "unknown"


def _infer_vendor_from_name(device_name: str) -> str:
    lower = device_name.lower()
    if any(token in lower for token in ["nvidia", "geforce", "rtx", "gtx"]):
        return "nvidia"
    if any(token in lower for token in ["amd", "radeon", "rx "]):
        return "amd"
    if "intel" in lower:
        return "intel"
    if "apple" in lower or "m1" in lower or "m2" in lower or "m3" in lower or "m4" in lower:
        return "apple"
    return "unknown"


def _detect_dml_support() -> bool:
    try:
        import onnxruntime as ort

        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def detect_hardware_profile() -> HardwareProfile:
    os_name = platform.system().lower()
    device_name = "unknown"

    if os_name == "windows":
        device_name = _detect_windows_gpu_name()
    elif os_name == "linux":
        device_name = _detect_linux_gpu_name()
    elif os_name == "darwin":
        device_name = _detect_macos_gpu_name()

    vendor = _infer_vendor_from_name(device_name)
    has_cuda = False
    has_mps = False
    has_rocm = False

    try:
        import torch

        has_cuda = bool(torch.cuda.is_available())
        has_mps = bool(
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )
        torch_version = getattr(torch.version, "hip", None)
        has_rocm = bool(torch_version)
    except Exception:
        pass

    return HardwareProfile(
        os_name=os_name,
        gpu_vendor=vendor,
        gpu_device_identity=device_name,
        has_cuda=has_cuda,
        has_vulkan=(Path(__file__).resolve().parent.parent / "vulkan_backend_spike" / "Qwen3-TTS-GGUF" / "qwen3_tts_gguf" / "inference" / "bin" / "ggml-vulkan.dll").exists()
        or os_name != "windows",
        has_dml=_detect_dml_support() if os_name == "windows" else False,
        has_mps=has_mps,
        has_rocm=has_rocm,
        vram_gb=None,
    )


def dispatch_real_probe(backend: BackendName) -> ProbeOutcome:
    if backend == "gguf":
        return probe_gguf_backend()
    if backend == "pytorch":
        return probe_pytorch_backend()
    raise ValueError(f"Unsupported backend: {backend}")


def bootstrap_backend_selection(
    *,
    env: dict[str, str] | None = None,
    cache_path: Path | None = None,
    hardware: HardwareProfile | None = None,
    versions: VersionProfile | None = None,
    probe_backend: ProbeFn | None = None,
) -> SelectionResult:
    env = env if env is not None else os.environ
    hardware = hardware or detect_hardware_profile()
    versions = versions or detect_version_profile()
    probe_backend = probe_backend or dispatch_real_probe
    cache_path = cache_path or get_probe_cache_path(os_name=hardware.os_name, env=env)
    cache_record = load_probe_cache(cache_path)

    result = select_backend(
        hardware=hardware,
        versions=versions,
        probe_backend=probe_backend,
        env=env,
        cache_record=cache_record,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    apply_backend_env(result.selection, env)
    if result.selection.source == "probe" and result.cache_record is not None:
        write_probe_cache(cache_path, result.cache_record)
    return result


def format_selection_log_line(selection: BackendSelection) -> str:
    return f"Selected backend: {selection.backend} (reason: {selection.reason})"


def probe_pytorch_backend(
    text: str = PROBE_TEXT,
    voice_id: str = PROBE_VOICE_ID,
) -> ProbeOutcome:
    # v0.1 thin-zip distribution does not ship PyTorch weights. If the
    # expected model directory is missing or empty, bail before the kernel
    # tries to load and crashes. Avoids a confusing "Loading Qwen3-TTS |
    # Device: CPU | Path: <missing>" trace on non-NVIDIA hardware that fell
    # through from a failed GGUF probe.
    model_dir = Path(__file__).resolve().parent / "bashi_tts_kernel" / "models" / MODEL_DEFAULT
    if not model_dir.exists() or not any(model_dir.iterdir()):
        return ProbeOutcome(
            False,
            "PyTorch model weights not present in this distribution "
            f"(expected at {model_dir}). PyTorch backend is reserved for "
            "NVIDIA CUDA setups; non-NVIDIA hardware should use GGUF."
        )

    start = time.perf_counter()
    service = None
    try:
        from local_tts_engine_pytorch import LocalTTSService

        service = LocalTTSService()
        audio, sample_rate = service._generate_wav_no_lock(text, voice_id)
        if audio is None or getattr(audio, "shape", (0,))[0] <= 0:
            return ProbeOutcome(False, "PyTorch probe produced empty audio")
        if sample_rate <= 0:
            return ProbeOutcome(False, f"PyTorch probe returned invalid sample rate: {sample_rate}")
        duration = time.perf_counter() - start
        return ProbeOutcome(True, f"PyTorch probe succeeded in {duration:.2f}s")
    except Exception as exc:
        return ProbeOutcome(False, f"PyTorch probe failed: {exc}")
    finally:
        if service is not None:
            try:
                service.shutdown()
            except Exception:
                pass


def probe_gguf_backend(
    text: str = PROBE_TEXT,
    voice_id: str = PROBE_VOICE_ID,
) -> ProbeOutcome:
    start = time.perf_counter()
    service = None
    try:
        from local_tts_engine_gguf import LocalTTSService

        service = LocalTTSService()
        audio, sample_rate = service._generate_wav_no_lock(text, voice_id)
        if audio is None or getattr(audio, "shape", (0,))[0] <= 0:
            return ProbeOutcome(False, "GGUF probe produced empty audio")
        if sample_rate <= 0:
            return ProbeOutcome(False, f"GGUF probe returned invalid sample rate: {sample_rate}")
        duration = time.perf_counter() - start
        return ProbeOutcome(True, f"GGUF probe succeeded in {duration:.2f}s")
    except Exception as exc:
        return ProbeOutcome(False, f"GGUF probe failed: {exc}")
    finally:
        if service is not None:
            try:
                service.shutdown()
            except Exception:
                pass


def run_real_probes(
    backends: list[BackendName] | None = None,
    text: str = PROBE_TEXT,
    voice_id: str = PROBE_VOICE_ID,
) -> dict[str, dict[str, object]]:
    backends = backends or ["gguf", "pytorch"]
    results: dict[str, dict[str, object]] = {}

    for backend in backends:
        started = time.perf_counter()
        if backend == "gguf":
            outcome = probe_gguf_backend(text=text, voice_id=voice_id)
        elif backend == "pytorch":
            outcome = probe_pytorch_backend(text=text, voice_id=voice_id)
        else:
            raise ValueError(f"Unsupported backend for probe harness: {backend}")

        results[backend] = {
            "success": outcome.success,
            "reason": outcome.reason,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }

    return results


def select_backend(
    hardware: HardwareProfile,
    versions: VersionProfile,
    probe_backend: ProbeFn,
    env: Mapping[str, str] | None = None,
    cache_record: ProbeCacheRecord | None = None,
    updated_at: str = "1970-01-01T00:00:00Z",
) -> SelectionResult:
    override = check_env_override(env)
    if override is not None:
        return SelectionResult(selection=override)

    cache_key = build_cache_key(hardware, versions)
    probe_order = tuple(get_probe_order(hardware))

    if (
        cache_record is not None
        and cache_record.cache_key == cache_key
        and cache_record.selected_backend in probe_order
    ):
        return SelectionResult(
            selection=BackendSelection(
                backend=cache_record.selected_backend,
                reason=f"cache hit: {cache_record.reason}",
                source="cache",
                cache_key=cache_key,
            ),
            cache_record=cache_record,
        )

    probe_log: list[str] = []
    attempted: list[BackendName] = []
    for backend in probe_order:
        attempted.append(backend)
        outcome = probe_backend(backend)
        probe_log.append(f"{backend}: {outcome.reason}")
        if not outcome.success:
            continue

        record = ProbeCacheRecord(
            cache_key=cache_key,
            selected_backend=backend,
            reason=outcome.reason,
            updated_at=updated_at,
        )
        return SelectionResult(
            selection=BackendSelection(
                backend=backend,
                reason=outcome.reason,
                source="probe",
                attempted_backends=tuple(attempted),
                cache_key=cache_key,
            ),
            cache_record=record,
            probe_log=tuple(probe_log),
        )

    raise BackendProbeError(
        "No backend passed preflight probe. Attempts: " + "; ".join(probe_log or ["none"])
    )


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Run backend preflight probes.")
    parser.add_argument(
        "--run-real-probes",
        action="store_true",
        help="Execute minimal real inference probes for one or more backends.",
    )
    parser.add_argument(
        "--backend",
        action="append",
        choices=["gguf", "pytorch"],
        help="Backend(s) to probe. Defaults to gguf + pytorch.",
    )
    parser.add_argument(
        "--text",
        default=PROBE_TEXT,
        help="Canonical probe text. Default: 你好。",
    )
    parser.add_argument(
        "--voice",
        default=PROBE_VOICE_ID,
        help="Voice id used for the probe. Default: uncle_fu",
    )
    args = parser.parse_args()

    if not args.run_real_probes:
        parser.print_help()
        return 0

    payload = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "results": run_real_probes(
            backends=args.backend,
            text=args.text,
            voice_id=args.voice,
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(item["success"] for item in payload["results"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
