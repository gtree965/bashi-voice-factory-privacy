import os


if os.environ.get("USE_GGUF_BACKEND") == "1":
    from local_tts_engine_gguf import OUTPUT_DIR, LocalTTSBusyError, LocalTTSError, service
else:
    from local_tts_engine_pytorch import OUTPUT_DIR, LocalTTSBusyError, LocalTTSError, service
