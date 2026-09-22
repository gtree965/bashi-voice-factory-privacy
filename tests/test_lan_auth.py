"""Tests for the LAN access PIN gate (``lan_auth``).

The suite drives a stand-in Flask app that mirrors the real route shapes
(index, JSON APIs, six SSE endpoints, download, static) and, for the rendered
home page, the real ``templates/index.html``.
"""

import ast
import contextlib
import hmac
import io
import logging
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, Response, jsonify, render_template

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import lan_auth  # noqa: E402

PORT = 5050
DEFAULT_HOST = "127.0.0.1:%d" % PORT
LOOPBACK_REMOTE = "127.0.0.1"
LAN_REMOTE = "192.168.1.50"
PIN_PAGE = "/lan-pin"

SSE_ENDPOINTS = (
    ("POST", "/api/cuda-upgrade/download"),
    ("POST", "/api/synthesize-long"),
    ("POST", "/api/synthesize-sentences"),
    ("POST", "/api/stt/download-model"),
    ("POST", "/api/stt/download-speaker-model"),
    ("GET", "/api/stt/progress/job-1"),
)


class FakeClock:
    """Injectable clock so the tests never depend on real time."""

    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class CountingHmac:
    """Stand-in for ``lan_auth.hmac``; records every PIN comparison."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def compare_digest(self, left, right):
        with self._lock:
            self.calls.append(left)
        return hmac.compare_digest(left, right)


def make_app():
    """Build a stand-in app plus the list that records reached handlers."""
    app = Flask("lan_auth_test", root_path=str(APP_ROOT))
    calls = []

    def view(name, mimetype=None):
        def handler(**_kwargs):
            calls.append(name)
            if mimetype:
                return Response("data: {}\n\n", mimetype=mimetype)
            if name == "index":
                return render_template("index.html", version="0.0.0-test")
            return jsonify({"ok": name})

        handler.__name__ = name
        return handler

    app.add_url_rule("/", "index", view("index"))
    app.add_url_rule("/api/voices", "voices", view("voices"))
    app.add_url_rule("/api/warmup/status", "warmup_status", view("warmup_status"))
    app.add_url_rule("/api/download/<filename>", "download", view("download"))
    app.add_url_rule("/api/stt/export/<job_id>", "export", view("export"))
    app.add_url_rule("/api/warmup", "warmup", view("warmup"), methods=["POST"])
    app.add_url_rule(
        "/api/stt/transcribe", "transcribe", view("transcribe"), methods=["POST"]
    )
    for method, path in SSE_ENDPOINTS:
        endpoint = "sse_%d" % len(app.view_functions)
        app.add_url_rule(
            path, endpoint, view(endpoint, mimetype="text/event-stream"),
            methods=[method],
        )
    return app, calls


def make_client(app, remote=LAN_REMOTE, host=DEFAULT_HOST, use_cookies=True):
    # use_cookies=False keeps the cookie jar from rewriting HTTP_COOKIE, which
    # it otherwise does per request host (werkzeug.test.Client).
    client = app.test_client(use_cookies=use_cookies)
    client.environ_base["REMOTE_ADDR"] = remote
    client.bashi_host = host
    return client


def call(client, method, path, extra_headers=None, **kwargs):
    headers = {"Host": client.bashi_host}
    if extra_headers:
        headers.update(extra_headers)
    return client.open(path, method=method, headers=headers, **kwargs)


def login(client, pin, remote=LAN_REMOTE):
    client.environ_base["REMOTE_ADDR"] = remote
    return call(client, "POST", PIN_PAGE, data={"pin": pin})


def cookie_from(response):
    return (response.headers.get("Set-Cookie") or "").split(";")[0]


class BindAddressTests(unittest.TestCase):
    def test_loopback_addresses(self):
        for value in ("127.0.0.1", "127.0.0.2", "127.255.255.254", "::1", "localhost"):
            with self.subTest(value=value):
                self.assertEqual(lan_auth.MODE_LOOPBACK, lan_auth.classify_bind_host(value))

    def test_lan_addresses(self):
        for value in ("0.0.0.0", "192.168.1.23", "10.0.0.7"):
            with self.subTest(value=value):
                self.assertEqual(lan_auth.MODE_LAN, lan_auth.classify_bind_host(value))

    def test_unsupported_addresses(self):
        for value in ("::", "fe80::1", "2001:db8::1", "mypc.local", "", "0:0:0:0:0:0:0:1"):
            with self.subTest(value=value):
                # 0:0:0:0:0:0:0:1 is ::1 written longhand and stays loopback.
                expected = (
                    lan_auth.MODE_LOOPBACK
                    if value == "0:0:0:0:0:0:0:1"
                    else lan_auth.MODE_UNSUPPORTED
                )
                self.assertEqual(expected, lan_auth.classify_bind_host(value))

    def test_unsupported_bind_host_exits_with_dedicated_code(self):
        logger = logging.getLogger("test.lan_auth.bind")
        for value in ("::", "fe80::1", "2001:db8::1", "mypc.local"):
            with self.subTest(value=value):
                with patch("builtins.print") as printer:
                    with self.assertRaises(SystemExit) as caught:
                        lan_auth.reject_unsupported_bind_host(value, logger=logger)
                self.assertEqual(lan_auth.BIND_HOST_REJECTED_EXIT_CODE, caught.exception.code)
                console = "\n".join(str(c.args[0]) for c in printer.call_args_list)
                self.assertIn("不支持的绑定地址", console)
                self.assertIn("仅支持以下绑定地址", console)
                self.assertNotIn("PIN", console)

    def test_supported_bind_host_is_not_rejected(self):
        for value in ("127.0.0.1", "localhost", "0.0.0.0", "192.168.1.23"):
            with self.subTest(value=value):
                lan_auth.reject_unsupported_bind_host(value)


class LoopbackModeTests(unittest.TestCase):
    def test_loopback_bind_leaves_responses_unchanged(self):
        unchanged_app, _ = make_app()
        app, _ = make_app()
        state = lan_auth.install(app, "127.0.0.1", PORT)

        probes = [
            ("GET", "/", None),
            ("GET", "/api/voices", None),
            ("GET", "/api/warmup/status", None),
            ("GET", "/static/js/app.js", None),
            ("POST", "/api/warmup", None),
        ]
        for method, path, _headers in probes:
            with self.subTest(path=path):
                expected = call(make_client(unchanged_app, remote=LOOPBACK_REMOTE), method, path)
                actual = call(make_client(app, remote=LOOPBACK_REMOTE), method, path)
                self.assertEqual(expected.status_code, actual.status_code)
                self.assertEqual(expected.get_data(), actual.get_data())

        self.assertFalse(state.enabled)
        self.assertIsNone(state.pin)
        self.assertIsNone(app.secret_key)

    def test_loopback_bind_sets_no_cookie(self):
        app, _ = make_app()
        lan_auth.install(app, "127.0.0.1", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        response = call(client, "GET", "/")

        self.assertEqual(200, response.status_code)
        self.assertNotIn("Set-Cookie", response.headers)

    def test_loopback_bind_has_no_pin_page(self):
        app, _ = make_app()
        lan_auth.install(app, "127.0.0.1", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        self.assertEqual(404, call(client, "GET", PIN_PAGE).status_code)


class LanGateTests(unittest.TestCase):
    def test_unauthenticated_navigation_redirects_to_the_pin_page(self):
        for bind in ("0.0.0.0", "192.168.1.23"):
            with self.subTest(bind=bind):
                app, _ = make_app()
                lan_auth.install(app, bind, PORT)
                client = make_client(app)

                response = call(
                    client, "GET", "/", {"Sec-Fetch-Mode": "navigate"}
                )

                self.assertEqual(302, response.status_code)
                self.assertEqual(PIN_PAGE, response.headers["Location"])
                self.assertNotIn("next", response.headers["Location"])

    def test_unauthenticated_api_returns_401_with_the_marker(self):
        for bind in ("0.0.0.0", "192.168.1.23"):
            with self.subTest(bind=bind):
                app, calls = make_app()
                lan_auth.install(app, bind, PORT)
                client = make_client(app)

                response = call(client, "GET", "/api/voices")

                self.assertEqual(401, response.status_code)
                self.assertEqual(lan_auth.UNAUTHORIZED_CODE, response.get_json()["code"])
                self.assertEqual([], calls)

    def test_all_six_sse_endpoints_are_blocked(self):
        app, calls = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        for method, path in SSE_ENDPOINTS:
            with self.subTest(path=path):
                calls.clear()
                response = call(client, method, path)
                self.assertEqual(401, response.status_code)
                self.assertEqual([], calls)

    def test_download_and_static_are_blocked(self):
        app, calls = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        for path in ("/api/download/sample.mp3", "/static/js/app.js"):
            with self.subTest(path=path):
                calls.clear()
                self.assertEqual(401, call(client, "GET", path).status_code)
                self.assertEqual([], calls)

    def test_export_navigation_redirects(self):
        app, calls = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = call(
            client, "GET", "/api/stt/export/job-1", {"Sec-Fetch-Mode": "navigate"}
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual(PIN_PAGE, response.headers["Location"])
        self.assertEqual([], calls)

    def test_pin_page_is_self_contained_and_carries_no_pin(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = call(client, "GET", PIN_PAGE)

        self.assertEqual(200, response.status_code)
        body = response.get_data(as_text=True)
        self.assertIn("<form", body)
        self.assertNotIn("/static/", body)
        self.assertNotIn(state.pin, body)
        self.assertIn("请输入局域网访问 PIN", body)
        self.assertEqual("no-store", response.headers["Cache-Control"])

    def test_correct_pin_unlocks_every_path(self):
        app, calls = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = login(client, state.pin)

        self.assertEqual(302, response.status_code)
        self.assertEqual("/", response.headers["Location"])
        # /static/* is served by Flask itself, so it records no handler call.
        self.assertEqual(200, call(client, "GET", "/static/js/app.js").status_code)
        for path in ("/api/voices", "/api/warmup/status"):
            with self.subTest(path=path):
                calls.clear()
                self.assertEqual(200, call(client, "GET", path).status_code)
                self.assertNotEqual([], calls)
        for method, path in SSE_ENDPOINTS:
            with self.subTest(path=path):
                calls.clear()
                self.assertEqual(200, call(client, method, path).status_code)
                self.assertNotEqual([], calls)

    def test_wrong_pin_counts_a_failure(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = login(client, "000000")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, state.limiter.failures_for(LAN_REMOTE))
        self.assertEqual(1, state.limiter.global_failures)
        self.assertIn("PIN", response.get_data(as_text=True))


class PinSubmissionBodyCheckTests(unittest.TestCase):
    """The submission is size and type checked before the body is parsed."""

    def setUp(self):
        self.app, self.calls = make_app()
        self.state = lan_auth.install(self.app, "0.0.0.0", PORT)
        self.client = make_client(self.app)
        self.spy = {"count": 0}
        original = self.app.view_functions["lan_pin"]

        def spy(*args, **kwargs):
            self.spy["count"] += 1
            return original(*args, **kwargs)

        self.app.view_functions["lan_pin"] = spy
        self.counter = CountingHmac()
        self.patcher = patch.object(lan_auth, "hmac", self.counter)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _assert_nothing_was_compared(self):
        self.assertEqual(0, self.spy["count"])
        self.assertEqual([], self.counter.calls)
        self.assertEqual(0, self.state.limiter.failures_for(LAN_REMOTE))
        self.assertEqual(0, self.state.limiter.global_failures)

    def test_oversized_body_is_rejected_with_413(self):
        response = call(
            self.client, "POST", PIN_PAGE, data={"pin": "0" * 2000}
        )

        self.assertEqual(413, response.status_code)
        self._assert_nothing_was_compared()

    def test_chunked_body_is_rejected_with_411(self):
        response = call(
            self.client,
            "POST",
            PIN_PAGE,
            extra_headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Transfer-Encoding": "chunked",
            },
            input_stream=io.BytesIO(b"pin=123456"),
        )

        self.assertEqual(411, response.status_code)
        self._assert_nothing_was_compared()

    def test_multipart_body_is_rejected_with_415(self):
        response = call(
            self.client,
            "POST",
            PIN_PAGE,
            data={"pin": "123456"},
            content_type="multipart/form-data",
        )

        self.assertEqual(415, response.status_code)
        self._assert_nothing_was_compared()

    def test_json_body_is_rejected_with_415(self):
        response = call(
            self.client, "POST", PIN_PAGE, json={"pin": "123456"}
        )

        self.assertEqual(415, response.status_code)
        self._assert_nothing_was_compared()

    def test_urlencoded_body_with_charset_is_accepted(self):
        response = call(
            self.client,
            "POST",
            PIN_PAGE,
            data={"pin": self.state.pin},
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual(1, self.spy["count"])

    def test_unauthenticated_large_upload_is_rejected_before_reading_the_body(self):
        response = call(
            self.client,
            "POST",
            "/api/stt/transcribe",
            extra_headers={"Content-Type": "multipart/form-data; boundary=xyz"},
            input_stream=io.BytesIO(b"x" * 4096),
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual([], self.calls)


class PerIpLockoutTests(unittest.TestCase):
    def test_lockout_after_the_limit_then_recovery(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        client = make_client(app)

        for _ in range(lan_auth.PER_IP_FAILURE_LIMIT):
            self.assertEqual(200, login(client, "000000").status_code)
        # Locked: even the correct PIN is refused, and it is not counted.
        self.assertEqual(200, login(client, state.pin).status_code)
        self.assertTrue(state.limiter.is_locked(LAN_REMOTE))
        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT, state.limiter.failures_for(LAN_REMOTE))

        clock.advance(lan_auth.PER_IP_LOCKOUT_SECONDS + 1)
        self.assertFalse(state.limiter.is_locked(LAN_REMOTE))
        self.assertEqual(0, state.limiter.failures_for(LAN_REMOTE))
        self.assertEqual(302, login(client, state.pin).status_code)

    def test_locked_submissions_do_not_count_or_extend(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        client = make_client(app)

        for _ in range(lan_auth.PER_IP_FAILURE_LIMIT):
            login(client, "000000")
        before_global = state.limiter.global_failures
        locked_until = clock.now + lan_auth.PER_IP_LOCKOUT_SECONDS

        clock.advance(lan_auth.PER_IP_LOCKOUT_SECONDS - 1)
        for _ in range(5):
            login(client, "000000")

        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT, state.limiter.failures_for(LAN_REMOTE))
        self.assertEqual(before_global, state.limiter.global_failures)
        self.assertEqual(locked_until, state.limiter._records[LAN_REMOTE].locked_until)

    def test_successful_login_clears_the_ip_failures(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        client = make_client(app)

        for _ in range(lan_auth.PER_IP_FAILURE_LIMIT - 1):
            login(client, "000000")
        self.assertEqual(302, login(client, state.pin).status_code)

        self.assertEqual(0, state.limiter.failures_for(LAN_REMOTE))
        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT - 1, state.limiter.global_failures)


class GlobalCooldownTests(unittest.TestCase):
    def test_cooldown_durations_double_up_to_the_cap(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        expected = [
            lan_auth.GLOBAL_COOLDOWN_BASE_SECONDS,
            lan_auth.GLOBAL_COOLDOWN_BASE_SECONDS * 2,
            lan_auth.GLOBAL_COOLDOWN_BASE_SECONDS * 4,
            lan_auth.GLOBAL_COOLDOWN_BASE_SECONDS * 8,
            lan_auth.GLOBAL_COOLDOWN_MAX_SECONDS,
            lan_auth.GLOBAL_COOLDOWN_MAX_SECONDS,
        ]
        observed = []
        for round_index in range(len(expected)):
            with self.subTest(round=round_index):
                while not state.limiter.is_cooling_down():
                    ip = "10.1.%d.%d" % (round_index, state.limiter.global_failures + 1)
                    client = make_client(app, remote=ip)
                    login(client, "000000", remote=ip)
                observed.append(state.limiter.cooldown_remaining())
                clock.advance(state.limiter.cooldown_remaining() + 1)

        self.assertEqual(expected, observed)
        self.assertEqual(len(expected), state.limiter.cooldown_level)

    def test_cooldown_expiry_clears_failures_but_keeps_the_level(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        while not state.limiter.is_cooling_down():
            ip = "10.2.0.%d" % (state.limiter.global_failures + 1)
            login(make_client(app, remote=ip), "000000", remote=ip)
        level = state.limiter.cooldown_level

        clock.advance(state.limiter.cooldown_remaining() + 1)
        ip = "10.2.1.1"
        login(make_client(app, remote=ip), "000000", remote=ip)

        self.assertEqual(1, state.limiter.global_failures)
        self.assertEqual(level, state.limiter.cooldown_level)

    def test_successful_login_does_not_reset_the_global_counters(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        for index in range(lan_auth.GLOBAL_FAILURE_LIMIT - 1):
            ip = "10.3.0.%d" % index
            login(make_client(app, remote=ip), "000000", remote=ip)
        good_client = make_client(app, remote="10.3.9.9")
        self.assertEqual(302, login(good_client, state.pin, remote="10.3.9.9").status_code)

        self.assertEqual(lan_auth.GLOBAL_FAILURE_LIMIT - 1, state.limiter.global_failures)
        self.assertEqual(0, state.limiter.cooldown_level)

        # One more failure is enough to start the (first) cooldown.
        ip = "10.3.0.200"
        login(make_client(app, remote=ip), "000000", remote=ip)
        self.assertTrue(state.limiter.is_cooling_down())
        self.assertEqual(lan_auth.GLOBAL_COOLDOWN_BASE_SECONDS, state.limiter.cooldown_remaining())

    def test_reinstall_resets_the_doubling_level(self):
        clock = FakeClock()
        app, _ = make_app()
        first = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        while not first.limiter.is_cooling_down():
            ip = "10.4.0.%d" % (first.limiter.global_failures + 1)
            login(make_client(app, remote=ip), "000000", remote=ip)
        self.assertEqual(1, first.limiter.cooldown_level)

        other_app, _ = make_app()
        second = lan_auth.install(other_app, "0.0.0.0", PORT, clock=clock)

        self.assertEqual(0, second.limiter.cooldown_level)
        self.assertEqual(0, second.limiter.global_failures)

    def test_cooldown_spares_signed_in_sessions_and_loopback(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        good = make_client(app, remote="10.5.0.1")
        self.assertEqual(302, login(good, state.pin, remote="10.5.0.1").status_code)

        while not state.limiter.is_cooling_down():
            ip = "10.5.1.%d" % (state.limiter.global_failures + 1)
            login(make_client(app, remote=ip), "000000", remote=ip)

        self.assertEqual(200, call(good, "GET", "/api/voices").status_code)
        loopback_client = make_client(app, remote=LOOPBACK_REMOTE)
        self.assertEqual(200, call(loopback_client, "GET", "/api/voices").status_code)

        fresh = make_client(app, remote="10.5.2.1")
        self.assertEqual(200, login(fresh, state.pin, remote="10.5.2.1").status_code)
        self.assertEqual(401, call(fresh, "GET", "/api/voices").status_code)


class ConcurrencyTests(unittest.TestCase):
    """The lock, the comparison and the counter update share one critical section."""

    def _run(self, threads):
        barrier = threading.Barrier(len(threads))
        results = [None] * len(threads)

        def worker(index, target):
            barrier.wait()
            results[index] = target()

        handles = [
            threading.Thread(target=worker, args=(index, target))
            for index, target in enumerate(threads)
        ]
        for handle in handles:
            handle.start()
        for handle in handles:
            handle.join(30)
        return results

    def test_same_ip_concurrent_failures_compare_exactly_the_ip_limit(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        counter = CountingHmac()

        def attempt():
            client = make_client(app)
            return login(client, "000000").status_code

        with patch.object(lan_auth, "hmac", counter):
            self._run([attempt for _ in range(40)])

        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT, len(counter.calls))
        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT, state.limiter.failures_for(LAN_REMOTE))

    def test_many_ips_concurrent_failures_compare_at_most_the_global_limit(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        counter = CountingHmac()

        def make_attempt(index):
            def attempt():
                client = make_client(app, remote="10.6.%d.%d" % (index // 250, index % 250 + 1))
                return login(client, "000000", remote=client.environ_base["REMOTE_ADDR"]).status_code

            return attempt

        with patch.object(lan_auth, "hmac", counter):
            self._run([make_attempt(i) for i in range(60)])

        self.assertLessEqual(len(counter.calls), lan_auth.GLOBAL_FAILURE_LIMIT)
        self.assertTrue(state.limiter.is_cooling_down())

    def test_locked_ip_refuses_a_correct_pin_racing_with_failures(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        for _ in range(lan_auth.PER_IP_FAILURE_LIMIT):
            login(make_client(app), "000000")
        self.assertTrue(state.limiter.is_locked(LAN_REMOTE))

        successes = []

        def wrong():
            client = make_client(app)
            return login(client, "000000").status_code

        def right():
            client = make_client(app)
            response = login(client, state.pin)
            successes.append(response.status_code)
            return response.status_code

        self._run([wrong for _ in range(10)] + [right])

        self.assertEqual([200], successes)
        self.assertEqual(lan_auth.PER_IP_FAILURE_LIMIT, state.limiter.failures_for(LAN_REMOTE))

    def test_cooling_down_refuses_a_correct_pin_from_a_fresh_ip(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        while not state.limiter.is_cooling_down():
            ip = "10.7.0.%d" % (state.limiter.global_failures + 1)
            login(make_client(app, remote=ip), "000000", remote=ip)

        successes = []

        def right():
            client = make_client(app, remote="10.7.9.9")
            response = login(client, state.pin, remote="10.7.9.9")
            successes.append(response.status_code)
            return response.status_code

        self._run([right])

        self.assertEqual([200], successes)


class SessionLifetimeTests(unittest.TestCase):
    def test_session_cookie_flags(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = login(client, state.pin)
        cookie = response.headers.get("Set-Cookie") or ""

        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Expires=", cookie)
        self.assertNotIn("Max-Age=", cookie)

    def test_session_dies_twelve_hours_after_login(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        client = make_client(app)

        self.assertEqual(302, login(client, state.pin).status_code)
        for _hour in range(12):
            clock.advance(3600)
            self.assertEqual(200, call(client, "GET", "/api/voices").status_code)

        clock.advance(1)
        self.assertEqual(401, call(client, "GET", "/api/voices").status_code)

    def test_restart_invalidates_the_old_session(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)
        client = make_client(app)

        response = login(client, state.pin)
        cookie = cookie_from(response)
        self.assertTrue(cookie.startswith("session="))

        restarted_app, _ = make_app()
        lan_auth.install(restarted_app, "0.0.0.0", PORT, clock=clock)
        restarted_client = make_client(restarted_app, use_cookies=False)

        self.assertEqual(
            401,
            call(restarted_client, "GET", "/api/voices", {"Cookie": cookie}).status_code,
        )


class LoopbackExemptionTests(unittest.TestCase):
    def test_loopback_remote_needs_no_pin_on_zero_bind(self):
        app, calls = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        self.assertEqual(200, call(client, "GET", "/api/voices").status_code)
        self.assertNotEqual([], calls)
        self.assertNotIn("Set-Cookie", call(client, "GET", "/api/voices").headers)

    def test_lan_remote_needs_a_pin_on_zero_bind(self):
        app, _ = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LAN_REMOTE)

        self.assertEqual(401, call(client, "GET", "/api/voices").status_code)

    def test_loopback_remote_needs_a_pin_when_bound_to_a_concrete_ip(self):
        app, _ = make_app()
        state = lan_auth.install(app, "192.168.1.23", PORT)

        self.assertFalse(state.loopback_reachable)
        for remote in ("127.0.0.1", "192.168.1.23"):
            with self.subTest(remote=remote):
                client = make_client(app, remote=remote)
                self.assertEqual(401, call(client, "GET", "/api/voices").status_code)


class HostHeaderTests(unittest.TestCase):
    """D6, applied in both loopback and LAN mode."""

    def _status(self, bind, host, path="/", method="GET"):
        """Status for a signed-in loopback caller, so only the Host check can fail."""
        app, _ = make_app()
        state = lan_auth.install(app, bind, PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE, use_cookies=False)
        headers = {"Host": host}
        if state.enabled:
            # Carried explicitly: the cookie jar keys on its own host, which is
            # not what these cases are probing.
            response = login(client, state.pin, remote=LOOPBACK_REMOTE)
            self.assertEqual(302, response.status_code)
            headers["Cookie"] = cookie_from(response)
        return call(client, method, path, headers).status_code

    def test_unknown_names_are_refused(self):
        for bind in ("127.0.0.1", "0.0.0.0", "192.168.1.23"):
            with self.subTest(bind=bind):
                self.assertEqual(400, self._status(bind, "evil.example:%d" % PORT))
                self.assertEqual(400, self._status(bind, "xxx.local:%d" % PORT))

    def test_port_mismatch_is_refused(self):
        self.assertEqual(400, self._status("0.0.0.0", "192.168.1.23:9999"))

    def test_missing_host_is_refused(self):
        self.assertEqual(400, self._status("0.0.0.0", ""))

    def test_host_without_port_is_refused(self):
        self.assertEqual(400, self._status("0.0.0.0", "127.0.0.1"))

    def test_loopback_names_and_literals_are_accepted(self):
        for bind in ("127.0.0.1", "0.0.0.0", "192.168.1.23"):
            for host in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT, "[::1]:%d" % PORT):
                with self.subTest(bind=bind, host=host):
                    self.assertEqual(200, self._status(bind, host))

    def test_zero_bind_accepts_any_ipv4_literal(self):
        self.assertEqual(200, self._status("0.0.0.0", "192.168.1.23:%d" % PORT))

    def test_concrete_bind_accepts_only_its_own_address(self):
        self.assertEqual(200, self._status("192.168.1.23", "192.168.1.23:%d" % PORT))
        self.assertEqual(400, self._status("192.168.1.23", "192.168.1.99:%d" % PORT))

    def test_refusal_happens_before_the_pin_page(self):
        app, calls = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        for method in ("GET", "POST"):
            with self.subTest(method=method):
                calls.clear()
                response = call(
                    client, method, PIN_PAGE, {"Host": "evil.example:%d" % PORT}
                )
                self.assertEqual(400, response.status_code)
                self.assertEqual([], calls)

        self.assertEqual(
            400,
            call(
                client,
                "POST",
                PIN_PAGE,
                {"Host": "evil.example:%d" % PORT},
                data={"pin": state.pin},
            ).status_code,
        )
        self.assertEqual(0, state.limiter.global_failures)


class LocalPinEndpointTests(unittest.TestCase):
    """D5: the PIN readout for the machine's own browser."""

    def test_loopback_caller_in_lan_mode_gets_the_pin(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        response = call(client, "GET", lan_auth.LOCAL_PIN_API_PATH)

        self.assertEqual(200, response.status_code)
        self.assertEqual(state.pin, response.get_json()["pin"])
        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.assertEqual("no-cache", response.headers["Pragma"])

    def test_non_loopback_caller_gets_404_not_401(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                app, _ = make_app()
                state = lan_auth.install(app, "0.0.0.0", PORT)
                client = make_client(app, remote=LAN_REMOTE)
                if authenticated:
                    self.assertEqual(302, login(client, state.pin).status_code)

                response = call(client, "GET", lan_auth.LOCAL_PIN_API_PATH)

                self.assertEqual(404, response.status_code)

    def test_navigation_request_gets_404_not_a_redirect(self):
        app, _ = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LAN_REMOTE)

        response = call(
            client,
            "GET",
            lan_auth.LOCAL_PIN_API_PATH,
            {"Sec-Fetch-Mode": "navigate"},
        )

        self.assertEqual(404, response.status_code)
        self.assertNotIn("Location", response.headers)

    def test_other_methods_and_cross_site_get_404(self):
        app, _ = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        self.assertEqual(
            404, call(client, "POST", lan_auth.LOCAL_PIN_API_PATH).status_code
        )
        self.assertEqual(
            404,
            call(
                client,
                "GET",
                lan_auth.LOCAL_PIN_API_PATH,
                {"Sec-Fetch-Site": "cross-site"},
            ).status_code,
        )

    def test_loopback_mode_and_concrete_bind_return_404(self):
        for bind in ("127.0.0.1", "192.168.1.23"):
            with self.subTest(bind=bind):
                app, _ = make_app()
                lan_auth.install(app, bind, PORT)
                client = make_client(app, remote=LOOPBACK_REMOTE)

                self.assertEqual(
                    404, call(client, "GET", lan_auth.LOCAL_PIN_API_PATH).status_code
                )

    def test_bad_host_is_refused_before_the_endpoint(self):
        app, _ = make_app()
        lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app, remote=LOOPBACK_REMOTE)

        response = call(
            client,
            "GET",
            lan_auth.LOCAL_PIN_API_PATH,
            {"Host": "evil.example:%d" % PORT},
        )

        self.assertEqual(400, response.status_code)


class CrossSiteTests(unittest.TestCase):
    """D7: state-changing requests have to come from our own page."""

    STATE_CHANGING = (
        ("POST", "/api/warmup"),
        ("POST", "/api/cuda-upgrade/download"),
        ("POST", "/api/stt/transcribe"),
    )
    FOREIGN_HEADERS = (
        ("cross-site", {"Sec-Fetch-Site": "cross-site"}),
        ("same-site", {"Sec-Fetch-Site": "same-site"}),
        ("foreign origin", {"Origin": "http://evil.example"}),
        ("null origin", {"Origin": "null"}),
    )

    def _request(self, bind, method, path, headers=None, remote=LAN_REMOTE, **kwargs):
        app, calls = make_app()
        state = lan_auth.install(app, bind, PORT)
        client = make_client(app, remote=remote)
        if state.enabled:
            self.assertEqual(302, login(client, state.pin, remote=remote).status_code)
        calls.clear()
        response = call(client, method, path, headers, **kwargs)
        return response, calls

    def test_foreign_requests_are_refused_in_both_modes(self):
        for bind in ("127.0.0.1", "0.0.0.0"):
            for label, headers in self.FOREIGN_HEADERS:
                for method, path in self.STATE_CHANGING:
                    with self.subTest(bind=bind, headers=label, path=path):
                        response, calls = self._request(bind, method, path, headers)
                        self.assertEqual(403, response.status_code)
                        self.assertEqual([], calls)

    def test_same_origin_and_headerless_clients_pass(self):
        for bind in ("127.0.0.1", "0.0.0.0"):
            for label, headers in (
                ("same-origin site", {"Sec-Fetch-Site": "same-origin"}),
                ("own origin", {"Origin": "http://%s" % DEFAULT_HOST}),
                ("no headers", None),
            ):
                with self.subTest(bind=bind, headers=label):
                    response, calls = self._request(
                        bind, "POST", "/api/warmup", headers
                    )
                    self.assertEqual(200, response.status_code)
                    self.assertEqual(["warmup"], calls)

    def test_get_requests_are_unaffected(self):
        for bind in ("127.0.0.1", "0.0.0.0"):
            with self.subTest(bind=bind):
                response, calls = self._request(
                    bind, "GET", "/api/voices", {"Sec-Fetch-Site": "cross-site"}
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual(["voices"], calls)

    def test_pin_submission_is_checked_too(self):
        for bind in ("0.0.0.0",):
            for label, headers in self.FOREIGN_HEADERS:
                with self.subTest(bind=bind, headers=label):
                    app, calls = make_app()
                    state = lan_auth.install(app, bind, PORT)
                    client = make_client(app)

                    response = call(
                        client, "POST", PIN_PAGE, headers, data={"pin": state.pin}
                    )

                    self.assertEqual(403, response.status_code)
                    self.assertEqual([], calls)
                    self.assertEqual(0, state.limiter.global_failures)

    def test_pin_submission_from_its_own_page_passes(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        response = call(
            client,
            "POST",
            PIN_PAGE,
            {"Sec-Fetch-Site": "same-origin"},
            data={"pin": state.pin},
        )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/", response.headers["Location"])


class FrontendPinHandlingTests(unittest.TestCase):
    """Static checks on the one front-end change this work is allowed to make."""

    def setUp(self):
        self.frontend = (APP_ROOT / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )

    def test_every_fetch_goes_through_the_wrapper(self):
        self.assertIn("const bashiRawFetch = window.fetch.bind(window);", self.frontend)
        self.assertIn("window.fetch = function bashiFetch(input, init) {", self.frontend)
        # The raw binding is the only way out of the wrapper, and the wrapper is
        # installed at load time, before init() can issue any request.
        self.assertEqual(
            1, self.frontend.count("const bashiRawFetch = window.fetch.bind(window);")
        )
        self.assertEqual(
            1, self.frontend.count("window.fetch = function bashiFetch(input, init) {")
        )

    def test_wrapper_looks_for_the_marker_without_consuming_the_body(self):
        section_start = self.frontend.index("window.fetch = function bashiFetch")
        section = self.frontend[section_start:section_start + 900]

        self.assertIn("response.status !== 401", section)
        self.assertIn("response.clone().json()", section)
        self.assertIn("payload.code === LAN_PIN_CODE", section)
        self.assertIn("return response;", section)

    def test_eventsource_error_starts_a_bounded_probe(self):
        self.assertIn("LAN_PIN_PROBE_INTERVAL_MS = 3000", self.frontend)
        self.assertIn("LAN_PIN_PROBE_TIMEOUT_MS = 300000", self.frontend)
        self.assertIn("bashiStartPinProbe();", self.frontend)

        onerror_start = self.frontend.index("eventSource.onerror = function() {")
        onerror = self.frontend[onerror_start:onerror_start + 500]
        # The interface reset has to stay first, unchanged.
        self.assertLess(onerror.index("eventSource.close();"), onerror.index("bashiStartPinProbe();"))
        self.assertIn("elements.sttTranscribeBtn.style.display = 'flex';", onerror)

    def test_home_page_asks_for_the_local_pin_once(self):
        self.assertIn("refreshLocalPinHint();", self.frontend)
        self.assertIn("'/api/local-pin'", self.frontend)
        init_start = self.frontend.index("async function init() {")
        init = self.frontend[init_start:init_start + 400]
        self.assertIn("refreshLocalPinHint();", init)


class PinSecrecyTests(unittest.TestCase):
    def test_pin_absent_from_logs_and_stderr(self):
        clock = FakeClock()
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT, clock=clock)

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                client = make_client(app)
                for _ in range(lan_auth.PER_IP_FAILURE_LIMIT):
                    login(client, "000000")
                clock.advance(lan_auth.PER_IP_LOCKOUT_SECONDS + 1)
                while not state.limiter.is_cooling_down():
                    ip = "10.8.0.%d" % (state.limiter.global_failures + 1)
                    login(make_client(app, remote=ip), "000000", remote=ip)
                clock.advance(state.limiter.cooldown_remaining() + 1)
                self.assertEqual(302, login(client, state.pin).status_code)
                self.assertEqual(200, call(client, "GET", "/").status_code)
                own = make_client(app, remote=LOOPBACK_REMOTE)
                self.assertEqual(
                    200, call(own, "GET", lan_auth.LOCAL_PIN_API_PATH).status_code
                )
        finally:
            root.removeHandler(handler)

        for text in (stdout.getvalue(), stderr.getvalue(), "\n".join(records)):
            self.assertNotIn(state.pin, text)

    def test_pin_absent_from_pages(self):
        app, _ = make_app()
        state = lan_auth.install(app, "0.0.0.0", PORT)
        client = make_client(app)

        pin_page = call(client, "GET", PIN_PAGE).get_data(as_text=True)
        self.assertNotIn(state.pin, pin_page)

        self.assertEqual(302, login(client, state.pin).status_code)
        home = call(client, "GET", "/").get_data(as_text=True)
        self.assertNotIn(state.pin, home)

    def test_no_logger_call_carries_the_pin(self):
        source = (APP_ROOT / "lan_auth.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        class PinVisitor(ast.NodeVisitor):
            def __init__(self):
                self.offenders = []

            def visit_Call(self, node):  # noqa: N802 - ast API naming
                func = node.func
                name = getattr(func, "attr", None)
                if name in {"debug", "info", "warning", "error", "exception", "critical"}:
                    for arg in list(node.args) + [kw.value for kw in node.keywords]:
                        for sub in ast.walk(arg):
                            if isinstance(sub, ast.Attribute) and sub.attr == "pin":
                                self.offenders.append(ast.unparse(node))
                            if isinstance(sub, ast.Name) and sub.id == "pin":
                                self.offenders.append(ast.unparse(node))
                self.generic_visit(node)

        visitor = PinVisitor()
        visitor.visit(tree)
        self.assertEqual([], visitor.offenders)


if __name__ == "__main__":
    unittest.main()
