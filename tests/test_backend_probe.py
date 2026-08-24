import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend_probe import (
    BackendOverrideConflictError,
    BackendProbeError,
    HardwareProfile,
    ProbeCacheRecord,
    ProbeOutcome,
    VersionProfile,
    _detect_windows_gpu_name,
    _infer_vendor_from_name,
    _run_isolated_probe,
    apply_backend_env,
    bootstrap_backend_selection,
    build_cache_key,
    check_env_override,
    detect_gguf_accelerator,
    dispatch_real_probe,
    format_selection_log_line,
    get_probe_cache_path,
    get_probe_order,
    load_probe_cache,
    probe_gguf_backend,
    run_real_probes,
    select_backend,
    write_probe_cache,
)


class BackendProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.windows_amd = HardwareProfile(
            os_name="windows",
            gpu_vendor="amd",
            gpu_device_identity="Radeon RX 590 Series",
            has_vulkan=True,
            has_dml=True,
            vram_gb=8,
        )
        self.versions = VersionProfile(
            torch_version="2.10.0",
            qwen3_tts_gguf_version="0.1.0",
            onnxruntime_version="1.22.0",
        )

    def test_conflicting_env_overrides_fail_loud(self) -> None:
        with self.assertRaises(BackendOverrideConflictError) as ctx:
            check_env_override({"USE_GGUF_BACKEND": "1", "USE_PYTORCH_BACKEND": "1"})

        self.assertIn("USE_GGUF_BACKEND=1", str(ctx.exception))
        self.assertIn("USE_PYTORCH_BACKEND=1", str(ctx.exception))

    def test_gguf_override_bypasses_probe(self) -> None:
        probe = Mock(side_effect=AssertionError("probe should not run"))

        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=probe,
            env={"USE_GGUF_BACKEND": "1"},
        )

        self.assertEqual(result.selection.backend, "gguf")
        self.assertEqual(result.selection.source, "override")
        probe.assert_not_called()

    def test_pytorch_override_bypasses_probe(self) -> None:
        probe = Mock(side_effect=AssertionError("probe should not run"))

        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=probe,
            env={"USE_PYTORCH_BACKEND": "1"},
        )

        self.assertEqual(result.selection.backend, "pytorch")
        self.assertEqual(result.selection.source, "override")
        probe.assert_not_called()

    def test_windows_gpu_vendors_with_vulkan_prefer_gguf_then_pytorch(self) -> None:
        for vendor, identity in (
            ("amd", "Radeon RX 590 Series"),
            ("intel", "Intel Arc A770"),
            ("nvidia", "NVIDIA A10"),
        ):
            with self.subTest(vendor=vendor):
                hardware = HardwareProfile(
                    os_name="windows",
                    gpu_vendor=vendor,
                    gpu_device_identity=identity,
                    has_cuda=False,
                    has_vulkan=True,
                    has_dml=True,
                    vram_gb=8,
                )
                self.assertEqual(get_probe_order(hardware), ["gguf", "pytorch"])

    def test_windows_gpu_name_prefers_nvidia_smi_rtx_5070_fixture(self) -> None:
        result = Mock(returncode=0, stdout="NVIDIA GeForce RTX 5070\n")

        with patch("backend_probe.subprocess.run", return_value=result) as run:
            device_name = _detect_windows_gpu_name()

        self.assertEqual(device_name, "NVIDIA GeForce RTX 5070")
        self.assertEqual(_infer_vendor_from_name(device_name), "nvidia")
        run.assert_called_once_with(
            [
                "nvidia-smi",
                "--query-gpu=name",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_windows_gpu_name_tries_nvidia_smi_fallback_paths(self) -> None:
        results = [
            FileNotFoundError(),
            Mock(returncode=0, stdout=""),
            Mock(returncode=0, stdout="NVIDIA GeForce RTX 5070\n"),
        ]

        with patch("backend_probe.subprocess.run", side_effect=results) as run:
            device_name = _detect_windows_gpu_name()

        self.assertEqual(device_name, "NVIDIA GeForce RTX 5070")
        self.assertEqual(
            [call.args[0][0] for call in run.call_args_list],
            [
                "nvidia-smi",
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            ],
        )

    def test_windows_gpu_name_stops_nvidia_smi_lookup_after_timeout(self) -> None:
        with patch(
            "backend_probe.subprocess.run",
            side_effect=[
                subprocess.TimeoutExpired("nvidia-smi", 5),
                Mock(returncode=0, stdout="HMvMonitorCloudPC Device\n"),
            ],
        ) as run:
            device_name = _detect_windows_gpu_name()

        self.assertEqual(device_name, "HMvMonitorCloudPC Device")
        self.assertEqual(
            [call.args[0][0] for call in run.call_args_list],
            ["nvidia-smi", "powershell"],
        )

    def test_windows_gpu_name_falls_back_to_wmi(self) -> None:
        def run_probe(command, **_kwargs):
            if command[0] == "powershell":
                return Mock(returncode=0, stdout="HMvMonitorCloudPC Device\n")
            return Mock(returncode=1, stdout="")

        with patch("backend_probe.subprocess.run", side_effect=run_probe) as run:
            device_name = _detect_windows_gpu_name(
                {"ProgramFiles": r"D:\Custom Program Files"}
            )

        self.assertEqual(device_name, "HMvMonitorCloudPC Device")
        self.assertEqual(
            [call.args[0][0] for call in run.call_args_list],
            [
                "nvidia-smi",
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                r"D:\Custom Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                "powershell",
            ],
        )

    def test_windows_nvidia_gguf_cuda_label_does_not_depend_on_torch_cuda(self) -> None:
        hardware = HardwareProfile(
            os_name="windows",
            gpu_vendor="nvidia",
            gpu_device_identity="NVIDIA GeForce RTX 5070",
            has_cuda=False,
            has_vulkan=True,
            has_dml=True,
            vram_gb=12,
        )

        with patch(
            "backend_probe.Path.exists",
            autospec=True,
            side_effect=lambda path: path.name in {"ggml-cuda.dll", "ggml-vulkan.dll"},
        ):
            accelerator = detect_gguf_accelerator(
                hardware,
                env={"GGUF_LLM_USE_GPU": "1"},
            )

        self.assertEqual(accelerator, "cuda")

    def test_linux_amd_rocm_prefers_pytorch(self) -> None:
        hardware = HardwareProfile(
            os_name="linux",
            gpu_vendor="amd",
            gpu_device_identity="Radeon Pro",
            has_rocm=True,
            has_vulkan=True,
            vram_gb=16,
        )
        self.assertEqual(get_probe_order(hardware), ["pytorch", "gguf"])

    def test_cache_hit_skips_probe(self) -> None:
        cache_record = ProbeCacheRecord(
            cache_key=build_cache_key(self.windows_amd, self.versions),
            selected_backend="gguf",
            reason="cached gguf pass",
            updated_at="2026-04-24T21:30:00Z",
        )
        probe = Mock(side_effect=AssertionError("probe should not run on cache hit"))

        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=probe,
            cache_record=cache_record,
        )

        self.assertEqual(result.selection.backend, "gguf")
        self.assertEqual(result.selection.source, "cache")
        probe.assert_not_called()

    def test_device_identity_change_invalidates_cache(self) -> None:
        stale_hardware = HardwareProfile(
            os_name="windows",
            gpu_vendor="amd",
            gpu_device_identity="Radeon RX 580 Series",
            has_vulkan=True,
            has_dml=True,
            vram_gb=8,
        )
        cache_record = ProbeCacheRecord(
            cache_key=build_cache_key(stale_hardware, self.versions),
            selected_backend="gguf",
            reason="cached gguf pass",
            updated_at="2026-04-24T21:30:00Z",
        )
        probe = Mock(return_value=ProbeOutcome(True, "fresh gguf pass"))

        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=probe,
            cache_record=cache_record,
            updated_at="2026-04-24T21:45:00Z",
        )

        self.assertEqual(result.selection.source, "probe")
        self.assertEqual(result.selection.backend, "gguf")
        probe.assert_called_once_with("gguf")

    def test_primary_failure_falls_back_to_secondary(self) -> None:
        def probe_backend(name: str) -> ProbeOutcome:
            if name == "gguf":
                return ProbeOutcome(False, "gguf probe failed")
            return ProbeOutcome(True, "pytorch cpu pass")

        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=probe_backend,
            updated_at="2026-04-24T22:00:00Z",
        )

        self.assertEqual(result.selection.backend, "pytorch")
        self.assertEqual(result.selection.source, "probe")
        self.assertEqual(result.selection.attempted_backends, ("gguf", "pytorch"))
        self.assertEqual(result.probe_log[0], "gguf: gguf probe failed")

    def test_all_probe_failures_raise_error(self) -> None:
        def probe_backend(name: str) -> ProbeOutcome:
            return ProbeOutcome(False, f"{name} failed")

        with self.assertRaises(BackendProbeError) as ctx:
            select_backend(
                hardware=self.windows_amd,
                versions=self.versions,
                probe_backend=probe_backend,
            )

        self.assertIn("gguf failed", str(ctx.exception))
        self.assertIn("pytorch failed", str(ctx.exception))

    def test_apply_backend_env_sets_single_backend(self) -> None:
        env = {"USE_GGUF_BACKEND": "1", "USE_PYTORCH_BACKEND": "1"}
        selection = check_env_override({"USE_GGUF_BACKEND": "1"})
        self.assertIsNotNone(selection)

        apply_backend_env(selection, env)

        self.assertEqual(env.get("USE_GGUF_BACKEND"), "1")
        self.assertNotIn("USE_PYTORCH_BACKEND", env)

    def test_probe_cache_round_trip(self) -> None:
        record = ProbeCacheRecord(
            cache_key=build_cache_key(self.windows_amd, self.versions),
            selected_backend="gguf",
            reason="cached gguf pass",
            updated_at="2026-04-24T22:15:00Z",
        )
        workspace_tmp = Path(__file__).resolve().parent / ".tmp"
        workspace_tmp.mkdir(exist_ok=True)
        path = workspace_tmp / "backend_probe_round_trip.json"
        if path.exists():
            path.unlink()
        try:
            write_probe_cache(path, record)
            loaded = load_probe_cache(path)
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(loaded, record)

    def test_probe_cache_path_follows_platform_conventions(self) -> None:
        windows_path = get_probe_cache_path(
            os_name="windows",
            env={"LOCALAPPDATA": r"C:\Users\alex1\AppData\Local"},
            home=Path(r"C:\Users\alex1"),
        )
        linux_path = get_probe_cache_path(
            os_name="linux",
            env={"XDG_CACHE_HOME": "/tmp/cache-home"},
            home=Path("/home/alex1"),
        )
        macos_path = get_probe_cache_path(
            os_name="macos",
            env={},
            home=Path("/Users/alex1"),
        )

        self.assertEqual(
            windows_path,
            Path(r"C:\Users\alex1\AppData\Local") / "bashi-privacy-app" / "backend_probe.json",
        )
        self.assertEqual(
            linux_path,
            Path("/tmp/cache-home") / "bashi-privacy-app" / "backend_probe.json",
        )
        self.assertEqual(
            macos_path,
            Path("/Users/alex1") / "Library" / "Caches" / "bashi-privacy-app" / "backend_probe.json",
        )

    def test_run_real_probes_uses_requested_backend_subset(self) -> None:
        with patch("backend_probe.probe_gguf_backend", return_value=ProbeOutcome(True, "gguf ok")) as gguf_probe:
            with patch("backend_probe.probe_pytorch_backend", return_value=ProbeOutcome(True, "pytorch ok")) as pytorch_probe:
                results = run_real_probes(backends=["gguf"], text="你好。", voice_id="uncle_fu")

        self.assertEqual(set(results.keys()), {"gguf"})
        self.assertTrue(results["gguf"]["success"])
        gguf_probe.assert_called_once_with(text="你好。", voice_id="uncle_fu")
        pytorch_probe.assert_not_called()

    def test_run_real_probes_collects_both_results(self) -> None:
        with patch("backend_probe.probe_gguf_backend", return_value=ProbeOutcome(False, "gguf missing runtime")):
            with patch("backend_probe.probe_pytorch_backend", return_value=ProbeOutcome(True, "pytorch ok")):
                results = run_real_probes(backends=["gguf", "pytorch"])

        self.assertFalse(results["gguf"]["success"])
        self.assertTrue(results["pytorch"]["success"])

    def test_gguf_probe_marks_permission_error_as_locked(self) -> None:
        fake_module = Mock()
        fake_module.LocalTTSService.side_effect = PermissionError("locked")

        with patch.dict(sys.modules, {"local_tts_engine_gguf": fake_module}):
            outcome = probe_gguf_backend()

        self.assertFalse(outcome.success)
        self.assertTrue(outcome.reason.startswith("[LOCKED]"))

    def test_gguf_probe_locked_marker_does_not_depend_on_english_strerror(self) -> None:
        localized_error = PermissionError(13, "拒绝访问。")
        self.assertNotIn("Permission denied", str(localized_error))
        fake_module = Mock()
        fake_module.LocalTTSService.side_effect = localized_error

        with patch.dict(sys.modules, {"local_tts_engine_gguf": fake_module}):
            outcome = probe_gguf_backend()

        self.assertFalse(outcome.success)
        self.assertTrue(outcome.reason.startswith("[LOCKED]"))

    def test_isolated_probe_parses_child_result(self) -> None:
        child = Mock(
            returncode=0,
            stdout='engine log\nBASHI_PROBE_RESULT={"success": true, "reason": "gguf ok"}\n',
            stderr="",
        )

        with patch("backend_probe.subprocess.run", return_value=child):
            outcome = _run_isolated_probe("gguf")

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.reason, "gguf ok")

    def test_isolated_probe_passes_openmp_workaround_to_child(self) -> None:
        child = Mock(
            returncode=0,
            stdout='BASHI_PROBE_RESULT={"success": true, "reason": "ok"}\n',
            stderr="",
        )

        with patch.dict(os.environ, {"PYTHONIOENCODING": "gbk"}):
            with patch("backend_probe.subprocess.run", return_value=child) as run:
                _run_isolated_probe("gguf")

        self.assertEqual(run.call_args.kwargs["env"]["KMP_DUPLICATE_LIB_OK"], "TRUE")
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")

    def test_isolated_probe_appends_stderr_tail_to_failed_result(self) -> None:
        child = Mock(
            returncode=1,
            stdout='BASHI_PROBE_RESULT={"success": false, "reason": "No audio"}\n',
            stderr="OMP Error #15: Initializing libomp140, but found libiomp5md already initialized.\n",
        )

        with patch("backend_probe.subprocess.run", return_value=child):
            outcome = _run_isolated_probe("gguf")

        self.assertFalse(outcome.success)
        self.assertIn("No audio", outcome.reason)
        self.assertIn("OMP Error #15", outcome.reason)

    def test_isolated_probe_does_not_append_stderr_to_success(self) -> None:
        child = Mock(
            returncode=0,
            stdout='BASHI_PROBE_RESULT={"success": true, "reason": "gguf ok"}\n',
            stderr="noisy native warning\n",
        )

        with patch("backend_probe.subprocess.run", return_value=child):
            outcome = _run_isolated_probe("gguf")

        self.assertTrue(outcome.success)
        self.assertEqual("gguf ok", outcome.reason)

    def test_isolated_probe_converts_native_crash_to_failure(self) -> None:
        child = Mock(
            returncode=0xC0000005,
            stdout="loading ggml-cuda.dll\n",
            stderr="",
        )

        with patch("backend_probe.subprocess.run", return_value=child):
            with patch("backend_probe.platform.system", return_value="Windows"):
                outcome = dispatch_real_probe("gguf")

        self.assertFalse(outcome.success)
        self.assertIn("0xC0000005", outcome.reason)
        self.assertIn("native CUDA/Vulkan/DirectML", outcome.reason)
        self.assertIn("loading ggml-cuda.dll", outcome.reason)

    def test_isolated_probe_converts_timeout_to_failure(self) -> None:
        with patch(
            "backend_probe.subprocess.run",
            side_effect=subprocess.TimeoutExpired("probe", 7),
        ):
            outcome = _run_isolated_probe("gguf", timeout_seconds=7)

        self.assertFalse(outcome.success)
        self.assertIn("timed out after 7s", outcome.reason)

    def test_bootstrap_runs_probe_and_writes_cache(self) -> None:
        workspace_tmp = Path(__file__).resolve().parent / ".tmp"
        workspace_tmp.mkdir(exist_ok=True)
        cache_path = workspace_tmp / "bootstrap_probe_cache.json"
        if cache_path.exists():
            cache_path.unlink()

        env = {}

        try:
            result = bootstrap_backend_selection(
                env=env,
                cache_path=cache_path,
                hardware=self.windows_amd,
                versions=self.versions,
                probe_backend=lambda backend: ProbeOutcome(True, f"{backend} ok"),
            )
            cached = load_probe_cache(cache_path)
        finally:
            if cache_path.exists():
                cache_path.unlink()

        self.assertEqual(result.selection.backend, "gguf")
        self.assertEqual(result.selection.source, "probe")
        self.assertEqual(env.get("USE_GGUF_BACKEND"), "1")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.selected_backend, "gguf")

    def test_bootstrap_cache_hit_skips_probe_and_applies_env(self) -> None:
        workspace_tmp = Path(__file__).resolve().parent / ".tmp"
        workspace_tmp.mkdir(exist_ok=True)
        cache_path = workspace_tmp / "bootstrap_cache_hit.json"
        record = ProbeCacheRecord(
            cache_key=build_cache_key(self.windows_amd, self.versions),
            selected_backend="gguf",
            reason="cached pass",
            updated_at="2026-04-24T23:00:00Z",
        )
        write_probe_cache(cache_path, record)
        env = {}
        probe = Mock(side_effect=AssertionError("probe should not run on cache hit"))

        try:
            result = bootstrap_backend_selection(
                env=env,
                cache_path=cache_path,
                hardware=self.windows_amd,
                versions=self.versions,
                probe_backend=probe,
            )
        finally:
            if cache_path.exists():
                cache_path.unlink()

        self.assertEqual(result.selection.source, "cache")
        self.assertEqual(env.get("USE_GGUF_BACKEND"), "1")
        probe.assert_not_called()

    def test_bootstrap_corrupt_cache_reprobes(self) -> None:
        workspace_tmp = Path(__file__).resolve().parent / ".tmp"
        workspace_tmp.mkdir(exist_ok=True)
        cache_path = workspace_tmp / "bootstrap_corrupt_cache.json"
        cache_path.write_text("{not-json", encoding="utf-8")
        env = {}
        probe = Mock(return_value=ProbeOutcome(True, "fresh probe"))

        try:
            result = bootstrap_backend_selection(
                env=env,
                cache_path=cache_path,
                hardware=self.windows_amd,
                versions=self.versions,
                probe_backend=probe,
            )
        finally:
            if cache_path.exists():
                cache_path.unlink()

        self.assertEqual(result.selection.source, "probe")
        probe.assert_called_once_with("gguf")
        self.assertEqual(env.get("USE_GGUF_BACKEND"), "1")

    def test_format_selection_log_line_is_user_facing(self) -> None:
        result = select_backend(
            hardware=self.windows_amd,
            versions=self.versions,
            probe_backend=lambda backend: ProbeOutcome(True, "gguf selected by probe"),
        )

        line = format_selection_log_line(result.selection)
        self.assertEqual(line, "Selected backend: gguf (reason: gguf selected by probe)")


if __name__ == "__main__":
    unittest.main()
