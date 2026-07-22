"""Download and verify the optional CUDA runtime add-on for the GGUF backend.

Primary source: ModelScope repository containing <platform>/manifest.json.

The CUDA bundle is an opt-in upgrade for NVIDIA users. When the DLLs are
present in vulkan_backend_spike/Qwen3-TTS-GGUF/qwen3_tts_gguf/inference/bin/
the GGUF runtime's ggml_backend_load_all() will prefer ggml-cuda.dll over
ggml-vulkan.dll automatically.

This module exposes two surfaces:
  * A streaming generator (download_cuda_runtime_streaming) that yields
    progress dicts matching the event shape used by model_manager — the
    Flask SSE route consumes this directly so the frontend's existing
    download UI works without modification.
  * A CLI entry point (main) for manual install / verification.

Dependency-free on purpose: must run inside the embedded Python before any
extra packages are installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Generator, Iterable, Mapping, Optional

from download_utils import SHA256_CHUNK_SIZE, sha256_file


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET_DIR = (
    APP_ROOT.parent
    / "vulkan_backend_spike"
    / "Qwen3-TTS-GGUF"
    / "qwen3_tts_gguf"
    / "inference"
    / "bin"
).resolve()
DEFAULT_MODELSCOPE_REPO = os.environ.get(
    "BASHI_CUDA_MODELSCOPE_REPO",
    "gtree592/bashi-qwen3-tts-cuda-runtime",
)
MANIFEST_FILENAME = "manifest.json"
LOCAL_MANIFEST_FILENAME = "cuda_runtime_manifest.json"
IDLE_TIMEOUT_SECONDS = 30.0
PROGRESS_INTERVAL_SECONDS = 0.5
DOWNLOAD_CHUNK_SIZE = 64 * 1024


class CudaRuntimeError(RuntimeError):
    pass


def detect_platform_subdir() -> str:
    """Return the ModelScope subdirectory for the current OS / arch.

    Raises CudaRuntimeError for platforms that don't have a CUDA bundle.
    """
    sys_platform = sys.platform
    machine = platform.machine().lower()
    if sys_platform.startswith("win") and machine in ("amd64", "x86_64"):
        return "win-x64"
    if sys_platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "linux-x64"
    if sys_platform == "darwin":
        raise CudaRuntimeError(
            "CUDA is not available on macOS. Apple Silicon uses Metal "
            "(bundled in the macOS release). Intel Mac is not supported."
        )
    raise CudaRuntimeError(
        f"No CUDA runtime bundle for platform={sys_platform} arch={machine}"
    )


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.replace("\\", "/").split("/"))


def modelscope_resolve_url(repo_id: str, path: str, revision: str = "master") -> str:
    encoded_repo = "/".join(urllib.parse.quote(part) for part in repo_id.strip("/").split("/"))
    return f"https://modelscope.cn/models/{encoded_repo}/resolve/{revision}/{_quote_path(path)}"


def _request(url: str, resume_at: int = 0) -> urllib.request.Request:
    headers = {"User-Agent": "BashiVoiceFactory-CUDA/0.1"}
    if resume_at > 0:
        headers["Range"] = f"bytes={resume_at}-"
    return urllib.request.Request(url, headers=headers)


def _progress_event(
    fname: str,
    files_done: int,
    total_files: int,
    bytes_done: int,
    bytes_total: Optional[int],
) -> dict:
    within_file = (bytes_done / bytes_total) if bytes_total else 0
    overall = ((files_done + within_file) / total_files) * 100 if total_files else 0
    mb_done = bytes_done / 1024 / 1024
    mb_total_text = f" / {bytes_total / 1024 / 1024:.1f} MB" if bytes_total else ""
    return {
        "status": "downloading",
        "file": fname,
        "file_index": files_done + 1,
        "total_files": total_files,
        "bytes_done": bytes_done,
        "bytes_total": bytes_total,
        "progress": round(overall, 1),
        "message": f"Downloading {fname}... {mb_done:.1f} MB{mb_total_text}",
        "message_zh": f"正在下载 {fname}... {mb_done:.1f} MB{mb_total_text}",
    }


def _stream_one_file(
    url: str,
    dest: Path,
    expected_sha256: Optional[str],
    fname: str,
    files_done: int,
    total_files: int,
) -> Generator[dict, None, None]:
    """Stream url -> dest with Range/resume + SHA256 verify. Yield progress events.

    .part is preserved on transient errors so a retry can resume. Only deleted
    when SHA256 fails (body was bad). On success the .part atomically replaces dest.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    resume_at = part.stat().st_size if part.exists() else 0
    mode = "ab" if resume_at else "wb"

    with urllib.request.urlopen(_request(url, resume_at), timeout=IDLE_TIMEOUT_SECONDS) as response:
        if resume_at and getattr(response, "status", None) != 206:
            resume_at = 0
            mode = "wb"

        total_header = response.headers.get("Content-Length")
        body_remaining = int(total_header) if total_header and total_header.isdigit() else None
        total_bytes = (body_remaining + resume_at) if body_remaining is not None else None

        downloaded = resume_at
        last_report = 0.0
        with part.open(mode) as out_file:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= PROGRESS_INTERVAL_SECONDS:
                    yield _progress_event(fname, files_done, total_files, downloaded, total_bytes)
                    last_report = now

        yield _progress_event(fname, files_done, total_files, downloaded, total_bytes)

    if expected_sha256:
        actual = sha256_file(part)
        if actual.lower() != expected_sha256.lower():
            part.unlink(missing_ok=True)
            raise CudaRuntimeError(
                f"Checksum mismatch for {dest.name}: "
                f"expected {expected_sha256[:12]}..., got {actual[:12]}..."
            )

    part.replace(dest)


def _fetch_manifest(repo_id: str, platform_subdir: str, revision: str) -> dict:
    url = modelscope_resolve_url(repo_id, f"{platform_subdir}/{MANIFEST_FILENAME}", revision)
    with urllib.request.urlopen(_request(url), timeout=IDLE_TIMEOUT_SECONDS) as response:
        body = response.read()
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CudaRuntimeError(f"CUDA manifest at {url} is not valid JSON: {exc}") from exc


def _manifest_files(manifest: Mapping) -> Iterable[dict]:
    files = manifest.get("files")
    if files is None:
        return []
    if not isinstance(files, list):
        raise CudaRuntimeError("CUDA manifest 'files' must be a list")
    return files


def _manifest_archives(manifest: Mapping) -> Iterable[dict]:
    archives = manifest.get("archives")
    if archives is None:
        return []
    if not isinstance(archives, list):
        raise CudaRuntimeError("CUDA manifest 'archives' must be a list")
    return archives


def _manifest_install_items(manifest: Mapping) -> list[dict]:
    install_items = list(_manifest_files(manifest))
    for archive in _manifest_archives(manifest):
        extracted = archive.get("extract")
        if not isinstance(extracted, list) or not extracted:
            raise CudaRuntimeError("CUDA archive manifest entry has no 'extract' list")
        install_items.extend(extracted)
    if not install_items:
        raise CudaRuntimeError("CUDA manifest has no installable files")
    return install_items


def _validate_relative_path(path: str) -> Path:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise CudaRuntimeError(f"Unsafe relative path in CUDA manifest: {path}")
    return rel


def _file_matches(path: Path, expected_sha256: Optional[str]) -> bool:
    if not path.exists():
        return False
    if not expected_sha256:
        return True
    try:
        return sha256_file(path).lower() == expected_sha256.lower()
    except OSError:
        return False


def _install_items_present(target_dir: Path, items: Iterable[Mapping]) -> bool:
    for item in items:
        rel = item.get("path")
        if not rel:
            return False
        dest = target_dir / _validate_relative_path(rel)
        if not _file_matches(dest, item.get("sha256")):
            return False
    return True


def _extract_zip_archive(archive_path: Path, target_dir: Path, extract_items: list[Mapping]) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        for item in extract_items:
            rel = item.get("path")
            if not rel:
                raise CudaRuntimeError("CUDA archive extract entry missing 'path'")
            dest_rel = _validate_relative_path(rel)
            member = item.get("member") or rel
            if member not in names:
                raise CudaRuntimeError(f"CUDA archive missing member: {member}")

            dest = target_dir / dest_rel
            if _file_matches(dest, item.get("sha256")):
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".extracting")
            with archive.open(member) as source, tmp.open("wb") as output:
                shutil.copyfileobj(source, output, SHA256_CHUNK_SIZE)

            expected_sha = item.get("sha256")
            if expected_sha and sha256_file(tmp).lower() != expected_sha.lower():
                tmp.unlink(missing_ok=True)
                raise CudaRuntimeError(f"Checksum mismatch after extracting {dest.name}")
            tmp.replace(dest)


def is_cuda_runtime_installed(target_dir: Path = DEFAULT_TARGET_DIR) -> bool:
    """Quick filesystem check: do we have a recorded CUDA manifest and all its files?

    Used by /api/cuda-upgrade/status to decide whether the upgrade button
    should be shown. Verifies SHA256 when the local manifest provides it.
    """
    manifest_path = target_dir / LOCAL_MANIFEST_FILENAME
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    try:
        return _install_items_present(target_dir, _manifest_install_items(manifest))
    except CudaRuntimeError:
        return False


def installed_manifest_summary(target_dir: Path = DEFAULT_TARGET_DIR) -> Optional[dict]:
    """Return a small dict describing the installed CUDA bundle, or None.

    Surfaced in /api/cuda-upgrade/status so the UI can display the llama.cpp
    build / CUDA version next to the upgrade chip.
    """
    manifest_path = target_dir / LOCAL_MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "platform": manifest.get("platform"),
        "llama_cpp_build": manifest.get("llama_cpp_build"),
        "cuda_version": manifest.get("cuda_version"),
        "file_count": len(_manifest_install_items(manifest)),
    }


def download_cuda_runtime_streaming(
    target_dir: Path = DEFAULT_TARGET_DIR,
    repo_id: str = DEFAULT_MODELSCOPE_REPO,
    platform_subdir: Optional[str] = None,
    revision: str = "master",
) -> Generator[dict, None, None]:
    """Generator-based downloader for Flask SSE consumption.

    Yields events with the same shape as model_manager so the frontend can
    reuse its existing download UI. The final event is {"status": "done"} on
    success or {"status": "error", "error": "..."} on failure.
    """
    try:
        platform_subdir = platform_subdir or detect_platform_subdir()
    except CudaRuntimeError as exc:
        yield {"status": "error", "error": str(exc)}
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    yield {
        "status": "downloading",
        "file": MANIFEST_FILENAME,
        "file_index": 0,
        "total_files": 1,
        "bytes_done": 0,
        "bytes_total": None,
        "progress": 0.0,
        "message": "Fetching CUDA manifest from ModelScope...",
        "message_zh": "正在从 ModelScope 获取 CUDA 清单...",
    }

    try:
        manifest = _fetch_manifest(repo_id, platform_subdir, revision)
        files = list(_manifest_files(manifest))
        archives = list(_manifest_archives(manifest))
        _manifest_install_items(manifest)
    except Exception as exc:
        yield {"status": "error", "error": f"Failed to fetch CUDA manifest: {exc}"}
        return

    entries = [{"kind": "file", "item": item} for item in files]
    entries.extend({"kind": "archive", "item": item} for item in archives)
    total_files = len(entries)
    files_done = 0

    for entry in entries:
        item = entry["item"]
        rel = item.get("path")
        expected_sha = item.get("sha256")
        if not rel:
            yield {"status": "error", "error": "CUDA manifest entry missing 'path'"}
            return

        dest = target_dir / _validate_relative_path(rel)
        # Skip raw file entries if already present and verified. Archive
        # entries are skipped only when every extracted install item is present.
        if entry["kind"] == "file" and _file_matches(dest, expected_sha):
            files_done += 1
            continue

        url = modelscope_resolve_url(repo_id, f"{platform_subdir}/{rel}", revision)

        yield {
            "status": "downloading",
            "file": rel,
            "file_index": files_done + 1,
            "total_files": total_files,
            "bytes_done": 0,
            "bytes_total": None,
            "progress": round((files_done / total_files) * 100, 1) if total_files else 0,
            "message": f"Starting {rel}...",
            "message_zh": f"开始下载 {rel}...",
        }

        try:
            if entry["kind"] == "archive":
                extracted = item.get("extract") or []
                if _install_items_present(target_dir, extracted):
                    files_done += 1
                    continue

                cache_dir = target_dir / ".cuda-runtime-cache"
                archive_dest = cache_dir / _validate_relative_path(rel).name
                if not _file_matches(archive_dest, expected_sha):
                    yield from _stream_one_file(
                        url,
                        archive_dest,
                        expected_sha,
                        rel,
                        files_done,
                        total_files,
                    )

                yield {
                    "status": "downloading",
                    "file": rel,
                    "file_index": files_done + 1,
                    "total_files": total_files,
                    "bytes_done": item.get("size"),
                    "bytes_total": item.get("size"),
                    "progress": round(((files_done + 1) / total_files) * 100, 1),
                    "message": f"Installing files from {rel}...",
                    "message_zh": f"正在安装 {rel} 内的文件...",
                }
                _extract_zip_archive(archive_dest, target_dir, extracted)
                archive_dest.unlink(missing_ok=True)
                try:
                    cache_dir.rmdir()
                except OSError:
                    pass
            else:
                yield from _stream_one_file(url, dest, expected_sha, rel, files_done, total_files)
        except Exception as exc:
            yield {"status": "error", "error": f"Download failed for {rel}: {exc}"}
            return

        files_done += 1

    # Save the manifest locally so is_cuda_runtime_installed() can verify
    # state on subsequent launches without hitting the network.
    try:
        (target_dir / LOCAL_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        yield {"status": "error", "error": f"Could not write local manifest: {exc}"}
        return

    yield {
        "status": "done",
        "platform": platform_subdir,
        "file_count": len(_manifest_install_items(manifest)),
        "message": "CUDA runtime installed. Restart the app to enable CUDA acceleration.",
        "message_zh": "CUDA 运行时已安装。请重启应用以启用 CUDA 加速。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the optional CUDA runtime bundle.")
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR), help="Destination inference/bin directory.")
    parser.add_argument("--modelscope-repo", default=DEFAULT_MODELSCOPE_REPO, help="ModelScope repo id.")
    parser.add_argument("--platform-subdir", default=None, help="Override the auto-detected platform subdirectory.")
    parser.add_argument("--revision", default="master", help="ModelScope revision/branch.")
    parser.add_argument("--check-only", action="store_true", help="Only verify an existing install.")
    args = parser.parse_args()

    target_dir = Path(args.target_dir).resolve()

    if args.check_only:
        if is_cuda_runtime_installed(target_dir):
            summary = installed_manifest_summary(target_dir) or {}
            print(f"CUDA runtime present at {target_dir}")
            if summary:
                print(f"  platform: {summary.get('platform')}")
                print(f"  llama.cpp build: {summary.get('llama_cpp_build')}")
                print(f"  CUDA: {summary.get('cuda_version')}")
                print(f"  files: {summary.get('file_count')}")
            return 0
        print(f"CUDA runtime not installed at {target_dir}")
        return 1

    last_progress = None
    for event in download_cuda_runtime_streaming(
        target_dir=target_dir,
        repo_id=args.modelscope_repo,
        platform_subdir=args.platform_subdir,
        revision=args.revision,
    ):
        status = event.get("status")
        if status == "downloading":
            msg = event.get("message", "")
            pct = event.get("progress")
            if pct is not None and last_progress != pct:
                print(f"  [{pct:5.1f}%] {msg}", end="\r")
                last_progress = pct
            elif msg:
                print(msg)
        elif status == "error":
            print()
            print(f"ERROR: {event.get('error')}", file=sys.stderr)
            return 1
        elif status == "done":
            print()
            print(event.get("message", "Done."))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
