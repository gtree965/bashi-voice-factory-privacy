import io
import logging
import os
import re
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import logging_setup
import werkzeug._internal


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = logging.getLogger()
        self.original_handlers = list(self.root.handlers)
        self.original_level = self.root.level
        self.had_ready_sentinel = hasattr(self.root, "_bashi_logging_ready")
        self.original_ready_sentinel = getattr(self.root, "_bashi_logging_ready", None)

        self.root.handlers.clear()
        if hasattr(self.root, "_bashi_logging_ready"):
            delattr(self.root, "_bashi_logging_ready")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "app.log"
        self.log_path_patcher = patch.object(logging_setup, "_LOG_PATH", self.log_path)
        self.log_path_patcher.start()

    def tearDown(self) -> None:
        for handler in self.root.handlers:
            handler.close()
        self.root.handlers.clear()
        if hasattr(self.root, "_bashi_logging_ready"):
            delattr(self.root, "_bashi_logging_ready")

        self.root.handlers.extend(self.original_handlers)
        self.root.setLevel(self.original_level)
        if self.had_ready_sentinel:
            self.root._bashi_logging_ready = self.original_ready_sentinel

        self.log_path_patcher.stop()
        self.temp_dir.cleanup()

    def test_get_logger_is_side_effect_free(self) -> None:
        logger = logging_setup.get_logger("tests.side_effect_free")

        self.assertEqual("tests.side_effect_free", logger.name)
        self.assertEqual([], self.root.handlers)
        self.assertFalse(hasattr(self.root, "_bashi_logging_ready"))
        self.assertFalse(self.log_path.exists())

    def test_setup_logging_is_idempotent_stdout_utf8_eager_and_rotating(self) -> None:
        console_stream = io.StringIO()
        with patch.dict(os.environ, {"BASHI_LOG_LEVEL": "DEBUG"}):
            with patch.object(sys, "stdout", console_stream):
                logging_setup.setup_logging()

        handlers_after_first_call = list(self.root.handlers)
        logging_setup.setup_logging()

        self.assertEqual(handlers_after_first_call, self.root.handlers)
        self.assertEqual(logging.DEBUG, self.root.level)
        self.assertTrue(getattr(self.root, "_bashi_logging_ready", False))
        self.assertEqual(2, len(self.root.handlers))

        file_handler = next(
            handler for handler in self.root.handlers if isinstance(handler, logging.FileHandler)
        )
        console_handler = next(
            handler for handler in self.root.handlers if not isinstance(handler, logging.FileHandler)
        )
        self.assertIs(console_stream, console_handler.stream)
        self.assertEqual("utf8", file_handler.encoding.lower().replace("-", ""))
        self.assertIsInstance(file_handler, logging_setup._SafeRotatingFileHandler)
        self.assertFalse(file_handler.delay)
        self.assertIsNotNone(file_handler.stream)
        self.assertEqual(2_000_000, file_handler.maxBytes)
        self.assertEqual(3, file_handler.backupCount)
        self.assertTrue(self.log_path.exists())

        logging_setup.get_logger("tests.logging_setup").info("中文 emoji 🔊")
        file_handler.flush()

        self.assertEqual("中文 emoji 🔊\n", console_stream.getvalue())
        file_text = self.log_path.read_text(encoding="utf-8")
        self.assertRegex(
            file_text,
            re.compile(
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
                r"\[INFO\] tests\.logging_setup: 中文 emoji 🔊\n$"
            ),
        )

    def test_setup_degrades_to_console_when_app_log_cannot_open(self) -> None:
        console_stream = io.StringIO()
        with patch.object(sys, "stdout", console_stream):
            with patch.object(
                logging_setup,
                "_SafeRotatingFileHandler",
                side_effect=PermissionError("locked"),
            ):
                logging_setup.setup_logging()

        self.assertTrue(getattr(self.root, "_bashi_logging_ready", False))
        self.assertEqual(1, len(self.root.handlers))
        self.assertIn("File logging disabled", console_stream.getvalue())
        self.assertIn("locked", console_stream.getvalue())

    def test_runtime_file_error_is_handled_without_propagating(self) -> None:
        handler = logging_setup._SafeRotatingFileHandler(
            self.log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        record = logging.LogRecord(
            name="tests.runtime_failure",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )

        try:
            with patch.object(RotatingFileHandler, "emit", side_effect=OSError("disk full")):
                with patch.object(handler, "handleError") as handle_error:
                    handler.emit(record)
        finally:
            handler.close()

        handle_error.assert_called_once_with(record)

    def test_werkzeug_uses_root_handlers_without_installing_a_duplicate(self) -> None:
        console_stream = io.StringIO()
        with patch.object(sys, "stdout", console_stream):
            logging_setup.setup_logging()

        original_werkzeug_logger = werkzeug._internal._logger
        werkzeug._internal._logger = None
        try:
            werkzeug._internal._log("info", '127.0.0.1 - - "GET / HTTP/1.1" 200 -')
            werkzeug_logger = logging.getLogger("werkzeug")

            self.assertEqual([], werkzeug_logger.handlers)
            self.assertEqual(1, console_stream.getvalue().count("GET / HTTP/1.1"))
            file_text = self.log_path.read_text(encoding="utf-8")
            self.assertEqual(1, file_text.count("GET / HTTP/1.1"))
        finally:
            werkzeug._internal._logger = original_werkzeug_logger


if __name__ == "__main__":
    unittest.main()
