import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOG_PATH = Path(__file__).resolve().parent / "app.log"
_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class _SafeRotatingFileHandler(RotatingFileHandler):
    """A logging failure must never propagate into application code."""

    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            self.handleError(record)


def setup_logging() -> None:
    """Configure root logging: plain console (stdout) + timestamped UTF-8 app.log.

    app.log is deliberately NOT launch_log.txt: run_portable.ps1 starts the app via
    ``cmd.exe /d /c "... 2>> launch_log.txt"``, and cmd.exe holds that file open for
    the whole life of the process. A FileHandler on the same path is denied by
    Windows (PermissionError) -- it crashed startup on every real launcher run until
    this split. Each file now has exactly one writer:
      * app.log        -- this handler (structured, timestamped, rotated)
      * launch_log.txt -- the launcher: [STEP] lines plus raw stderr we do not
                          control (Python tracebacks, native llama.cpp/ggml output)
    Console goes to stdout so the launcher's stderr redirect never doubles it.
    """
    root = logging.getLogger()
    if getattr(root, "_bashi_logging_ready", False):
        return

    level = os.environ.get("BASHI_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    root.addHandler(console)

    # Opened eagerly (no delay=True) so an unusable path degrades to console-only
    # here instead of raising from the first logger call deep inside the app.
    try:
        file_handler = _SafeRotatingFileHandler(
            _LOG_PATH,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        root.addHandler(file_handler)
    except Exception as exc:  # pragma: no cover - depends on filesystem state
        root.warning("File logging disabled (%s): %s", _LOG_PATH, exc)

    root._bashi_logging_ready = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger without configuring global logging."""
    return logging.getLogger(name)
