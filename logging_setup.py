import logging
import os
import sys
from pathlib import Path


_LOG_PATH = Path(__file__).resolve().parent / "launch_log.txt"
_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging() -> None:
    """Configure root logging: plain console (stdout) + timestamped UTF-8 file.

    Console goes to stdout on purpose: run_portable.ps1 already redirects
    stderr (2>>) into launch_log.txt, so a stderr console handler would write
    every line twice.

    NOTE: launch_log.txt has two complementary writers, by design --
    (1) this FileHandler (structured, timestamped app logs), and
    (2) the launcher's ``2>>`` redirect, which captures raw stderr we do not
        control: Python tracebacks and native llama.cpp/ggml output.
    Neither is the sole writer; they do not overlap.
    """
    root = logging.getLogger()
    if getattr(root, "_bashi_logging_ready", False):
        return

    level = os.environ.get("BASHI_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    root.addHandler(console)

    file_handler = logging.FileHandler(
        _LOG_PATH,
        mode="a",
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    root._bashi_logging_ready = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger without configuring global logging."""
    return logging.getLogger(name)
