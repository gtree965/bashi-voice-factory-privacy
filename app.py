"""
Bashi Voice Factory Privacy Edition
Flask-based local TTS/STT app with Qwen3 local TTS and sherpa-onnx STT.
"""

import os

# --- Environment hardening (must precede all heavy imports) ---
# OMP Error #15: torch libiomp5md x ggml libomp140 duplicate runtimes.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# Best-effort UTF-8 for this process's own stdio and non-isolated children such
# as the probe subprocess. Isolated mp-spawn workers ignore PYTHON* env via -I;
# local_tts_engine_gguf.py injects command-line -X utf8=1 for those workers.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import argparse
import sys

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
        logger.error("[Backend Selector] Startup aborted: %s", exc)
        raise SystemExit(2)
    except BackendProbeError as exc:
        app_root = os.path.dirname(os.path.abspath(__file__))
        app_log_path = os.path.join(app_root, "app.log")
        launcher_log_path = os.path.join(app_root, "launch_log.txt")
        sep = "=" * 60
        logger.error(sep)
        logger.error("[Backend Selector] No usable backend was found.")
        logger.error("  Detail: %s", exc)
        logger.error("")
        logger.error("Most common causes / 常见原因:")
        logger.error("  - GGUF runtime model files missing or corrupted —")
        logger.error("    re-run the launcher to re-download from ModelScope.")
        logger.error("    GGUF 运行模型文件缺失或损坏 —— 请重新运行启动器从 ModelScope 下载。")
        logger.error("  - Vulkan / DirectML drivers outdated — update GPU driver.")
        logger.error("    Vulkan / DirectML 驱动过旧 —— 请更新显卡驱动。")
        logger.error("  - Insufficient RAM (need >= 8 GB free for 1.7B model).")
        logger.error("    内存不足（1.7B 模型需要至少 8 GB 可用内存）。")
        logger.error("")
        logger.error(
            "  Full logs: %s (application), %s (launcher)",
            app_log_path,
            launcher_log_path,
        )
        logger.error(
            "  完整日志: %s（应用）, %s（启动器）",
            app_log_path,
            launcher_log_path,
        )
        logger.error(sep)
        raise SystemExit(3)

    logger.info(format_selection_log_line(result.selection))


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
    logger.info("本地隐私版：Qwen3 本地语音 + sherpa 离线转写")
    logger.info("=" * 50)

    if args.host == "0.0.0.0":
        logger.info("Starting server at http://0.0.0.0:%s (Network Accessible)", args.port)
    else:
        logger.info("Starting server at http://%s:%s (Local Only)", args.host, args.port)

    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)

    if os.environ.get("LOCAL_TTS_WARMUP_ON_START") == "1":
        logger.info("Warming up local TTS engine...")
        from local_tts_engine import service

        service.warmup()
        logger.info("Warmup complete.")

    app.run(debug=False, host=args.host, port=args.port)
