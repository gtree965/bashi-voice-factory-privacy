"""
Bashi Voice Factory Privacy Edition
Flask-based local TTS/STT app with Qwen3 local TTS and sherpa-onnx STT.
"""

import argparse
import os
import sys

from flask import Flask, render_template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_probe import (  # noqa: E402
    BackendOverrideConflictError,
    BackendProbeError,
    bootstrap_backend_selection,
    format_selection_log_line,
)
from utils import cleanup_old_files  # noqa: E402


def create_app() -> Flask:
    from stt_routes import UPLOAD_DIR, stt_bp
    from tts_routes import OUTPUT_DIR, VERSION, tts_bp

    app = Flask(__name__)
    app.config["BASHI_OUTPUT_DIR"] = OUTPUT_DIR
    app.config["BASHI_UPLOAD_DIR"] = UPLOAD_DIR
    app.config["BASHI_VERSION"] = VERSION

    app.register_blueprint(tts_bp)
    app.register_blueprint(stt_bp)

    @app.route("/")
    def index():
        return render_template("index.html", version=VERSION)

    return app


def _bootstrap_backend_or_exit() -> None:
    try:
        result = bootstrap_backend_selection()
    except BackendOverrideConflictError as exc:
        print(f"[Backend Selector] Startup aborted: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except BackendProbeError as exc:
        print(f"[Backend Selector] Startup aborted: {exc}", file=sys.stderr)
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
