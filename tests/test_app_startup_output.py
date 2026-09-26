"""S2: no framework start-up banner, and the LAN address sits next to the PIN.

The banner test starts a real Flask server on the installed Flask/Werkzeug and
checks both sinks the banner used to reach: the console (Flask echoes its two
lines with click, Werkzeug logs through the ``werkzeug`` logger) and app.log
(the same records, propagated to the root file handler).
"""

import contextlib
import io
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from flask import Flask

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as app_module  # noqa: E402
import lan_auth  # noqa: E402


BANNER_FRAGMENTS = (
    "Running on",
    "development server",
    "Serving Flask app",
    "Press CTRL+C",
)
ACCESS_LOG_MARKER = '"GET / HTTP/1.1" 200'


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request_until_ready(port: int, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:%d/" % port, timeout=1.0
            ) as response:
                return response.read().decode("utf-8")
        except OSError as exc:  # connection refused while the thread starts up
            last_error = exc
            time.sleep(0.05)
    raise AssertionError("server did not answer on port %d: %s" % (port, last_error))


def _wait_for_access_log(console: io.StringIO, log_path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        file_text = log_path.read_text(encoding="utf-8", errors="replace")
        if ACCESS_LOG_MARKER in console.getvalue() and ACCESS_LOG_MARKER in file_text:
            return True
        time.sleep(0.05)
    return False


class FrameworkStartupBannerTests(unittest.TestCase):
    def test_banner_is_silent_on_the_console_and_in_the_log_file(self) -> None:
        console_stream = io.StringIO()
        console_handler = logging.StreamHandler(console_stream)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        previous_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(console_handler)

        printed = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "app.log"
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(file_handler)
            try:
                application = Flask("banner_test")
                application.add_url_rule("/", "index", lambda: "ok")

                app_module._silence_framework_startup_banner()
                port = _free_port()
                server = threading.Thread(
                    target=application.run,
                    kwargs={
                        "debug": False,
                        "host": "127.0.0.1",
                        "port": port,
                        "load_dotenv": False,
                        "use_reloader": False,
                    },
                    daemon=True,
                )
                # The banner is written before the server accepts anything, so
                # once the request below succeeds it has already been emitted
                # and could only have gone into these two sinks.
                with contextlib.redirect_stdout(printed):
                    server.start()
                    body = _request_until_ready(port)
                self.assertEqual("ok", body)
                self.assertTrue(
                    _wait_for_access_log(console_stream, log_path),
                    "the access log line never reached the console and the file",
                )
                file_text = log_path.read_text(encoding="utf-8", errors="replace")
            finally:
                root.removeHandler(file_handler)
                file_handler.close()

        root.removeHandler(console_handler)
        root.setLevel(previous_level)

        console_text = console_stream.getvalue()
        for sink, text in (
            ("console", console_text),
            ("stdout", printed.getvalue()),
            ("app.log", file_text),
        ):
            for fragment in BANNER_FRAGMENTS:
                with self.subTest(sink=sink, fragment=fragment):
                    self.assertNotIn(fragment, text)
        self.assertIn(ACCESS_LOG_MARKER, console_text)
        self.assertIn(ACCESS_LOG_MARKER, file_text)

    def test_banner_suppression_is_installed_before_app_run(self) -> None:
        source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        main_source = source[source.index('if __name__ == "__main__":') :]

        self.assertLess(
            main_source.index("_silence_framework_startup_banner()"),
            main_source.index("app.run("),
        )
        self.assertIn("flask.cli.show_server_banner", source)
        self.assertIn('logging.getLogger("werkzeug")', source)


class LanAccessAddressTests(unittest.TestCase):
    def _announce(self, bind_host, port, environment):
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=False):
            if "BASHI_LAN_DISPLAY_HOST" not in environment:
                os.environ.pop("BASHI_LAN_DISPLAY_HOST", None)
            with contextlib.redirect_stdout(output):
                app_module._announce_lan_access_address(bind_host, port)
        return output.getvalue()

    def test_launcher_value_is_printed_as_a_url(self) -> None:
        text = self._announce(
            "0.0.0.0", 5050, {"BASHI_LAN_DISPLAY_HOST": "192.168.1.52"}
        )

        self.assertIn("http://192.168.1.52:5050", text)

    def test_concrete_bind_address_is_used_without_the_launcher_value(self) -> None:
        text = self._announce("192.168.1.52", 5050, {})

        self.assertIn("http://192.168.1.52:5050", text)

    def test_unknown_address_points_at_the_launcher_output(self) -> None:
        text = self._announce("0.0.0.0", 5050, {})

        self.assertIn("见上方启动器输出", text)
        self.assertNotIn("http://", text)

    def test_launcher_value_with_whitespace_is_not_used(self) -> None:
        text = self._announce(
            "0.0.0.0", 5050, {"BASHI_LAN_DISPLAY_HOST": " 192.168.1.52 extra"}
        )

        self.assertIn("见上方启动器输出", text)
        self.assertNotIn("http://", text)

    def test_address_is_printed_next_to_the_pin_block_and_the_pin_stays_out_of_logs(self) -> None:
        application = Flask("lan_address_test")
        state = lan_auth.install(application, "0.0.0.0", 5050)

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        output = io.StringIO()
        try:
            with patch.dict(
                os.environ, {"BASHI_LAN_DISPLAY_HOST": "192.168.1.52"}, clear=False
            ), contextlib.redirect_stdout(output):
                app_module._announce_lan_access_address("0.0.0.0", 5050)
                state.announce_pin()
        finally:
            root.removeHandler(handler)

        lines = output.getvalue().splitlines()
        address_index = next(
            index
            for index, line in enumerate(lines)
            if "http://192.168.1.52:5050" in line
        )
        pin_index = next(
            index for index, line in enumerate(lines) if line.strip() == state.pin
        )

        self.assertLess(address_index, pin_index)
        self.assertLessEqual(pin_index - address_index, 8)
        self.assertNotIn(state.pin, "\n".join(records))
        self.assertNotIn(state.pin, "\n".join(lines[:address_index]))

    def test_main_announces_the_address_only_in_lan_mode(self) -> None:
        source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        main_source = source[source.index('if __name__ == "__main__":') :]

        self.assertIn("if lan_state.enabled:", main_source)
        self.assertLess(
            main_source.index("_announce_lan_access_address(args.host, args.port)"),
            main_source.index("lan_state.announce_pin()"),
        )
        self.assertLess(
            main_source.index("if lan_state.enabled:"),
            main_source.index("_announce_lan_access_address(args.host, args.port)"),
        )


if __name__ == "__main__":
    unittest.main()
