"""
Bashi Voice Factory Privacy Edition
Flask-based local TTS/STT app with Qwen3 local TTS and sherpa-onnx STT.
"""

import os

# --- Environment hardening (must precede all heavy imports) ---
# OMP Error #15: torch libiomp5md x ggml libomp140 duplicate runtimes.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# GGUF decoder/speaker workers (mp.Process spawn) print emoji; without
# explicit UTF-8, a GBK console codepage kills them via UnicodeEncodeError.
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
from utils import cleanup_old_files  # noqa: E402


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
        print(f"[Backend Selector] Startup aborted: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except BackendProbeError as exc:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch_log.txt")
        sep = "=" * 60
        print(sep, file=sys.stderr)
        print("[Backend Selector] No usable backend was found.", file=sys.stderr)
        print(f"  Detail: {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Most common causes / 常见原因:", file=sys.stderr)
        print("  - GGUF runtime model files missing or corrupted —", file=sys.stderr)
        print("    re-run the launcher to re-download from ModelScope.", file=sys.stderr)
        print("    GGUF 运行模型文件缺失或损坏 —— 请重新运行启动器从 ModelScope 下载。", file=sys.stderr)
        print("  - Vulkan / DirectML drivers outdated — update GPU driver.", file=sys.stderr)
        print("    Vulkan / DirectML 驱动过旧 —— 请更新显卡驱动。", file=sys.stderr)
        print("  - Insufficient RAM (need >= 8 GB free for 1.7B model).", file=sys.stderr)
        print("    内存不足（1.7B 模型需要至少 8 GB 可用内存）。", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"  Full probe log: {log_path}", file=sys.stderr)
        print(f"  完整探测日志: {log_path}", file=sys.stderr)
        print(sep, file=sys.stderr)
        raise SystemExit(3)

    print(format_selection_log_line(result.selection))


if __name__ == "__main__":
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

    print("=" * 50)
    print(f"Bashi Voice Factory Privacy Edition v{version}")
    print("Local TTS: Qwen3-TTS-12Hz-1.7B-CustomVoice")
    print("本地隐私版：Qwen3 本地语音 + sherpa 离线转写")
    print("=" * 50)

    if args.host == "0.0.0.0":
        print(f"Starting server at http://0.0.0.0:{args.port} (Network Accessible)")
    else:
        print(f"Starting server at http://{args.host}:{args.port} (Local Only)")

    print("Press Ctrl+C to stop")
    print("=" * 50)

    if os.environ.get("LOCAL_TTS_WARMUP_ON_START") == "1":
        print("Warming up local TTS engine...")
        from local_tts_engine import service

        service.warmup()
        print("Warmup complete.")

    app.run(debug=False, host=args.host, port=args.port)
