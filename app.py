"""
Bashi Voice Factory Privacy Edition
Flask-based local TTS/STT app with Qwen3 local TTS and sherpa-onnx STT.
"""

import os

# --- Environment hardening (must precede all heavy imports) ---
# OMP Error #15: torch libiomp5md x ggml libomp140 duplicate runtimes.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# Best-effort UTF-8 for subsequent non-isolated Python children. Setting this
# after interpreter startup does not reconfigure this process's existing stdio.
# Isolated mp-spawn workers ignore PYTHON* env via -I; local_tts_engine_gguf.py
# injects command-line -X utf8=1 for those workers.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import argparse
import sys
import time

from flask import Flask, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_probe import (  # noqa: E402
    BackendOverrideConflictError,
    BackendProbeError,
    bootstrap_backend_selection,
    format_selection_log_line,
)
from logging_setup import get_logger, setup_logging  # noqa: E402
from utils import cleanup_old_files  # noqa: E402


logger = get_logger(__name__)


def _ascii_log_text(value: object) -> str:
    """Preserve localized details in an ASCII-safe form for app.log."""
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def _probe_failure_causes(detail: str) -> tuple[list[str], list[str]]:
    """Return separate English-log and Chinese-console failure causes."""
    english_causes = [
        "  - GGUF runtime model files missing or corrupted -",
        "    re-run the launcher to re-download from ModelScope.",
        "  - Vulkan / DirectML drivers outdated - update GPU driver.",
        "  - Insufficient RAM (need >= 8 GB free for 1.7B model).",
    ]
    chinese_causes = [
        "  - GGUF 运行模型文件缺失或损坏 —— 请重新运行启动器从 ModelScope 下载。",
        "  - Vulkan / DirectML 驱动过旧 —— 请更新显卡驱动。",
        "  - 内存不足（1.7B 模型需要至少 8 GB 可用内存）。",
    ]
    if "[LOCKED]" in detail:
        english_causes.insert(
            0,
            "  - Another copy may already be running - close it and try again.",
        )
        chinese_causes.insert(
            0,
            "  - 可能已有另一个副本正在运行 —— 请先关闭它再重试。",
        )
    return english_causes, chinese_causes


def _elapsed_since_epoch_ms(env_name: str) -> float | None:
    raw_epoch_ms = os.environ.get(env_name)
    if not raw_epoch_ms:
        return None
    try:
        epoch_ms = int(raw_epoch_ms)
        elapsed_ms = (time.time_ns() // 1_000_000) - epoch_ms
    except (TypeError, ValueError, OverflowError):
        return None
    if epoch_ms <= 0 or elapsed_ms < 0:
        return None
    return elapsed_ms / 1000.0


def _log_launcher_handoff_elapsed() -> None:
    """Log launcher-to-app.run handoff timings when the launcher stamped them."""
    launcher_elapsed = _elapsed_since_epoch_ms("BASHI_LAUNCH_EPOCH")
    if launcher_elapsed is not None:
        logger.info(
            "[Startup Timing] launcher_to_app_run_handoff_seconds=%.3f",
            launcher_elapsed,
        )

    deps_ready_elapsed = _elapsed_since_epoch_ms("BASHI_DEPS_READY_EPOCH")
    if deps_ready_elapsed is not None:
        logger.info(
            "[Startup Timing] deps_ready_to_app_run_handoff_seconds=%.3f",
            deps_ready_elapsed,
        )


def _run_startup_warmup_if_requested() -> None:
    """Best-effort startup warmup; optimization failure must not abort the app."""
    if os.environ.get("LOCAL_TTS_WARMUP_ON_START") != "1":
        return

    logger.info("Warming up local TTS engine...")
    try:
        from tts_routes import run_warmup_synchronously

        status = run_warmup_synchronously()
    except Exception as exc:
        logger.warning(
            "Local TTS warmup failed; continuing server startup: %s",
            _ascii_log_text(exc),
        )
        return

    state = status.get("state")
    if state == "ready":
        logger.info("Warmup complete.")
    elif state == "warming":
        logger.warning(
            "Local TTS warmup exceeded the startup wait; continuing while it runs."
        )
    else:
        logger.warning(
            "Local TTS warmup did not complete; continuing server startup: state=%s error=%s",
            _ascii_log_text(state or "unknown"),
            _ascii_log_text(status.get("error") or "unknown"),
        )


def create_app() -> Flask:
    from stt_routes import MAX_UPLOAD_BYTES, UPLOAD_DIR, stt_bp
    from tts_routes import OUTPUT_DIR, VERSION, tts_bp

    app = Flask(__name__)
    # Transport-level backstop: also catches chunked uploads that carry no
    # Content-Length. 1 MiB slack covers the multipart envelope so the
    # friendly per-route check in stt_routes stays the user-facing limit.
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024
    app.config["BASHI_OUTPUT_DIR"] = OUTPUT_DIR
    app.config["BASHI_UPLOAD_DIR"] = UPLOAD_DIR
    app.config["BASHI_VERSION"] = VERSION

    app.register_blueprint(tts_bp)
    app.register_blueprint(stt_bp)

    @app.route("/")
    def index():
        return render_template("index.html", version=VERSION)

    @app.errorhandler(413)
    def request_entity_too_large(error):
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({"error": f"File too large. Maximum upload size is {max_mb} MB."}), 413

    return app


def _bootstrap_backend_or_exit() -> None:
    try:
        result = bootstrap_backend_selection()
    except BackendOverrideConflictError as exc:
        logger.error("[Backend Selector] Startup aborted: %s", _ascii_log_text(exc))
        raise SystemExit(2)
    except BackendProbeError as exc:
        app_root = os.path.dirname(os.path.abspath(__file__))
        app_log_path = os.path.join(app_root, "app.log")
        launcher_log_path = os.path.join(app_root, "launch_log.txt")
        sep = "=" * 60
        english_causes, chinese_causes = _probe_failure_causes(str(exc))
        logger.error(sep)
        logger.error("[Backend Selector] No usable backend was found.")
        logger.error("  Detail: %s", _ascii_log_text(exc))
        print(f"  详细信息: {exc}")
        logger.error("")
        logger.error("Most common causes:")
        for cause_line in english_causes:
            logger.error(cause_line)
        print("常见原因:")
        for cause_line in chinese_causes:
            print(cause_line)
        logger.error("")
        logger.error(
            "  Full logs: %s (application), %s (launcher)",
            _ascii_log_text(app_log_path),
            _ascii_log_text(launcher_log_path),
        )
        print(f"  完整日志: {app_log_path}（应用）, {launcher_log_path}（启动器）")
        logger.error(sep)
        raise SystemExit(3)

    logger.info(_ascii_log_text(format_selection_log_line(result.selection)))


if __name__ == "__main__":
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Bashi Voice Factory Privacy Edition (巴适声工厂隐私版)"
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP to bind to")
    parser.add_argument("--port", type=int, default=5050, help="Port to bind to")
    args = parser.parse_args()

    _bootstrap_backend_or_exit()
    app = create_app()

    output_dir = app.config["BASHI_OUTPUT_DIR"]
    upload_dir = app.config["BASHI_UPLOAD_DIR"]
    version = app.config["BASHI_VERSION"]

    cleanup_old_files(output_dir, max_age_hours=24)
    cleanup_old_files(upload_dir, max_age_hours=24)

    logger.info("=" * 50)
    logger.info("Bashi Voice Factory Privacy Edition v%s", version)
    logger.info("Local TTS: Qwen3-TTS-12Hz-1.7B-CustomVoice")
    print("本地隐私版：Qwen3 本地语音 + sherpa 离线转写")
    logger.info("=" * 50)

    if args.host == "0.0.0.0":
        logger.info("Starting server at http://0.0.0.0:%s (Network Accessible)", args.port)
    else:
        logger.info("Starting server at http://%s:%s (Local Only)", args.host, args.port)

    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)

    _log_launcher_handoff_elapsed()

    _run_startup_warmup_if_requested()

    app.run(debug=False, host=args.host, port=args.port)
