"""S4: the mirror speed test, driven by local http.server stand-ins.

Every case runs mirror_probe.py as its own process against a local server, the
way the launcher runs it - including the cases that measure how long the
process takes to leave.
"""

import http.server
import json
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import mirror_probe  # noqa: E402

MIB = 1024 * 1024
PROBE_SCRIPT = APP_ROOT / "mirror_probe.py"


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean
        pass

    def do_GET(self):
        server = self.server
        server.request_count += 1
        behavior = server.behavior

        if behavior == "accept_then_close":
            # Whatever the OS does with a port that has no listener (this
            # machine drops the SYN, others answer with RST), an answer that
            # arrives and then closes without a response is the portable way
            # to reach the conn status.
            self.close_connection = True
            return

        if behavior == "http_403":
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if behavior == "short_read":
            payload = b"x" * 1024
            self.send_response(206)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self._write(payload)
            return

        if behavior == "premature_close":
            self.send_response(206)
            self.send_header("Content-Length", str(MIB))
            self.end_headers()
            self._write(b"x" * 4096)
            self.close_connection = True
            return

        if behavior == "drip":
            self.send_response(200)
            self.send_header("Content-Length", str(4 * MIB))
            self.end_headers()
            try:
                for _ in range(100000):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(server.drip_interval)
            except OSError:
                return
            return

        if behavior == "ignores_range":
            payload = b"y" * (4 * MIB)
        else:
            payload = b"z" * MIB

        if server.delay_seconds:
            time.sleep(server.delay_seconds)
        self.send_response(200 if behavior == "ignores_range" else 206)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self._write(payload)

    def _write(self, payload, chunk=64 * 1024):
        try:
            for offset in range(0, len(payload), chunk):
                block = payload[offset : offset + chunk]
                self.wfile.write(block)
                self.wfile.flush()
                with self.server.sent_lock:
                    self.server.sent_bytes += len(block)
        except OSError:
            return


class ProbeServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.behavior = "ok"
        self.delay_seconds = 0.0
        self.drip_interval = 0.5
        self.sent_bytes = 0
        self.sent_lock = threading.Lock()
        self.request_count = 0

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def probe_url(self) -> str:
        return "http://127.0.0.1:%d/%s" % (self.port, mirror_probe.PROBE_WHEEL)

    @property
    def index_url(self) -> str:
        return "http://127.0.0.1:%d/simple/" % self.port

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


def _candidate(name: str, probe_url: str, index_url: str = "http://127.0.0.1:1/simple/") -> dict:
    return {"name": name, "index_url": index_url, "probe_url": probe_url}


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ProbeStatusMappingTests(unittest.TestCase):
    """The status codes, including the refusal path that cannot be forced here.

    A connection refused by the OS is not reproducible on every machine: this
    one drops the SYN to a local port with no listener and the connect times
    out instead. The classification is therefore tested directly, and the
    process tests use a server that closes without answering for conn.
    """

    def test_url_error_reasons_map_to_the_documented_statuses(self):
        cases = (
            ("conn", urllib.error.URLError(ConnectionRefusedError(10061, "refused"))),
            ("timeout", urllib.error.URLError(TimeoutError("timed out"))),
            ("timeout", urllib.error.URLError(socket.timeout("timed out"))),
            ("tls", urllib.error.URLError(ssl.SSLError("handshake failed"))),
            ("conn", urllib.error.URLError(OSError("no route to host"))),
        )
        for expected, error in cases:
            with self.subTest(expected=expected, error=repr(error)):
                self.assertEqual(expected, mirror_probe._status_from_url_error(error))

    def test_unreachable_candidate_is_a_failure_not_a_success(self):
        port = _unused_port()

        with tempfile.TemporaryDirectory() as directory:
            candidates_path = Path(directory) / "candidates.json"
            candidates_path.write_text(
                json.dumps([_candidate("unreachable", "http://127.0.0.1:%d/x" % port)]),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_SCRIPT),
                    "--candidates-json",
                    str(candidates_path),
                    "--socket-timeout",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(1, result.returncode)
        self.assertNotIn("ok", result.stdout)
        self.assertNotIn("://", result.stdout)
        self.assertNotIn("Traceback", result.stdout)


class ProbeProcessTestCase(unittest.TestCase):
    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def make_server(self, behavior="ok", **attributes) -> ProbeServer:
        server = ProbeServer()
        server.behavior = behavior
        for name, value in attributes.items():
            setattr(server, name, value)
        server.start()
        self.servers.append(server)
        return server

    def run_probe(self, candidates, extra_args=(), timeout=40):
        with tempfile.TemporaryDirectory() as directory:
            candidates_path = Path(directory) / "candidates.json"
            candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
            command = [
                sys.executable,
                str(PROBE_SCRIPT),
                "--candidates-json",
                str(candidates_path),
            ]
            command.extend(extra_args)
            started = time.monotonic()
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout
            )
            elapsed = time.monotonic() - started

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        ranks = [
            line.split(" ", 2)[2].split(",")
            for line in lines
            if line.startswith("%s %s " % (mirror_probe.LINE_PREFIX, mirror_probe.RANK_MARKER))
        ]
        self.assertEqual(1, len(ranks), "expected exactly one rank line:\n" + result.stdout)
        return result, elapsed, lines, ranks[0]

    def assert_diagnostics_are_clean(self, output: str) -> None:
        self.assertNotIn("://", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("Error", output)
        for line in output.splitlines():
            if line.strip():
                self.assertTrue(line.isascii(), line)
                self.assertTrue(line.startswith(mirror_probe.LINE_PREFIX + " "), line)


class ProbeRankingTests(ProbeProcessTestCase):
    def test_range_aware_mirror_is_ok_and_reads_exactly_one_mebibyte(self):
        server = self.make_server("ok")

        result, _elapsed, lines, ranked = self.run_probe(
            [_candidate("good", server.probe_url, server.index_url)]
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual(["good"], ranked)
        self.assertIn("[mirror-probe] good ok ", lines[0])
        self.assertEqual(MIB, server.sent_bytes)
        self.assert_diagnostics_are_clean(result.stdout)

    def test_faster_mirror_comes_first(self):
        slow = self.make_server("ok", delay_seconds=1.5)
        fast = self.make_server("ok")

        result, _elapsed, _lines, ranked = self.run_probe(
            [
                _candidate("slow", slow.probe_url, slow.index_url),
                _candidate("fast", fast.probe_url, fast.index_url),
            ]
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual(["fast", "slow"], ranked)

    def test_server_that_ignores_the_range_header_is_capped_at_one_mebibyte(self):
        server = self.make_server("ignores_range")

        result, _elapsed, _lines, ranked = self.run_probe(
            [_candidate("no-range", server.probe_url, server.index_url)]
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual(["no-range"], ranked)
        self.assertGreaterEqual(server.sent_bytes, MIB)
        self.assertLess(
            server.sent_bytes,
            3 * MIB,
            "the probe kept reading past its 1 MiB cap: %d bytes left the server"
            % server.sent_bytes,
        )

    def test_failures_follow_the_successes_in_their_original_order(self):
        forbidden = self.make_server("http_403")
        good = self.make_server("ok")
        closed = self.make_server("accept_then_close")

        result, _elapsed, lines, ranked = self.run_probe(
            [
                _candidate("forbidden", forbidden.probe_url, forbidden.index_url),
                _candidate("good", good.probe_url, good.index_url),
                _candidate("closed", closed.probe_url, closed.index_url),
            ]
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual(["good", "forbidden", "closed"], ranked)
        self.assertIn("[mirror-probe] forbidden http_403", lines)
        self.assertIn("[mirror-probe] closed conn", lines)
        self.assert_diagnostics_are_clean(result.stdout)

    def test_tls_failure_is_reported_without_an_exception_text(self):
        server = self.make_server("ok")

        result, _elapsed, _lines, ranked = self.run_probe(
            [_candidate("tls-down", server.probe_url.replace("http://", "https://"))]
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual(["tls-down"], ranked)
        self.assertIn("[mirror-probe] tls-down tls", result.stdout)
        self.assert_diagnostics_are_clean(result.stdout)

    def test_body_that_stops_early_is_a_short_read(self):
        server = self.make_server("premature_close")

        result, _elapsed, _lines, ranked = self.run_probe(
            [_candidate("cut", server.probe_url, server.index_url)]
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual(["cut"], ranked)
        self.assertIn("[mirror-probe] cut short_read", result.stdout)

    def test_all_failures_keep_the_fixed_order_and_exit_nonzero(self):
        forbidden = self.make_server("http_403")
        closed = self.make_server("accept_then_close")

        result, _elapsed, _lines, ranked = self.run_probe(
            [
                _candidate("first", forbidden.probe_url, forbidden.index_url),
                _candidate("second", closed.probe_url, closed.index_url),
            ]
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual(["first", "second"], ranked)


class ProbeDeadlineTests(ProbeProcessTestCase):
    def test_slow_drip_hits_the_per_source_deadline_and_the_process_leaves(self):
        server = self.make_server("drip", drip_interval=0.5)

        result, elapsed, lines, ranked = self.run_probe(
            [_candidate("drip", server.probe_url, server.index_url)]
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual(["drip"], ranked)
        self.assertIn("[mirror-probe] drip timeout", lines)
        self.assertLess(elapsed, 12.0, "process took %.1fs" % elapsed)
        self.assertGreater(elapsed, 6.0, "process took %.1fs" % elapsed)

    def test_a_worker_that_never_finishes_is_cut_at_the_global_deadline(self):
        server = self.make_server("drip", drip_interval=0.5)

        result, elapsed, lines, ranked = self.run_probe(
            [_candidate("drip", server.probe_url, server.index_url)],
            extra_args=("--per-source-deadline", "600", "--global-deadline", "10"),
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual(["drip"], ranked)
        self.assertIn("[mirror-probe] drip timeout", lines)
        self.assertLess(elapsed, 13.0, "process took %.1fs" % elapsed)
        self.assertGreater(elapsed, 9.0, "process took %.1fs" % elapsed)


class ProbeUnitTests(unittest.TestCase):
    def test_rank_puts_successes_first_by_time_and_keeps_failure_order(self):
        results = [
            mirror_probe.ProbeResult("a", "http_403"),
            mirror_probe.ProbeResult("b", "ok", 2.0),
            mirror_probe.ProbeResult("c", "timeout"),
            mirror_probe.ProbeResult("d", "ok", 1.0),
        ]

        ranked = mirror_probe.rank_results(results)

        self.assertEqual(["d", "b", "a", "c"], [result.name for result in ranked])

    def test_output_lines_are_ascii_and_stable(self):
        self.assertEqual(
            "[mirror-probe] aliyun ok 1.23s",
            mirror_probe.format_result_line(
                mirror_probe.ProbeResult("aliyun", "ok", 1.234)
            ),
        )
        self.assertEqual(
            "[mirror-probe] tuna http_403",
            mirror_probe.format_result_line(mirror_probe.ProbeResult("tuna", "http_403")),
        )
        ranked = [
            mirror_probe.ProbeResult("aliyun", "ok", 1.0),
            mirror_probe.ProbeResult("pypi", "timeout"),
        ]
        self.assertEqual(
            "[mirror-probe] rank aliyun,pypi",
            mirror_probe.format_rank_line(ranked),
        )

    def test_default_candidates_are_the_five_mirrors_and_the_pinned_wheel(self):
        requirements = (APP_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("numpy==1.26.4", requirements)
        self.assertEqual(
            ["aliyun", "tuna", "tencent", "huawei", "pypi"],
            [candidate.name for candidate in mirror_probe.DEFAULT_CANDIDATES],
        )
        for candidate in mirror_probe.DEFAULT_CANDIDATES:
            with self.subTest(candidate=candidate.name):
                self.assertTrue(candidate.index_url.startswith("https://"))
                self.assertTrue(candidate.probe_url.startswith("https://"))
                self.assertIn(mirror_probe.PROBE_WHEEL_PATH, candidate.probe_url)
                self.assertIn("numpy-1.26.4-cp312-cp312-win_amd64.whl", candidate.probe_url)

    def test_no_candidate_disables_certificate_verification(self):
        source = PROBE_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("verify=False", source)
        self.assertNotIn("ssl._create_unverified_context", source)
        self.assertNotIn("CERT_NONE", source)

    def test_launcher_catalog_matches_the_probe_candidates(self):
        launcher_catalog = _launcher_variable(
            "$pipMirrorIndexUrls", "mirror_probe_launcher_catalog_test"
        )
        expected = {
            candidate.name: candidate.index_url
            for candidate in mirror_probe.DEFAULT_CANDIDATES
        }

        self.assertEqual(expected, json.loads(launcher_catalog))


def _launcher_variable(variable_name: str, _label: str) -> str:
    """Read one top-level variable assignment out of run_portable.ps1."""
    launcher = APP_ROOT / "run_portable.ps1"
    escaped_path = str(launcher).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
        "[ref]$tokens, [ref]$errors); "
        "$assignment=$ast.Find({param($node) $node -is "
        "[System.Management.Automation.Language.AssignmentStatementAst] -and "
        f"$node.Left.Extent.Text -eq '{variable_name}'}}, $true); "
        "Invoke-Expression $assignment.Extent.Text; "
        f"{variable_name} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    unittest.main()
