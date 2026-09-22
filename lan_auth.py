"""
One-time PIN gate for non-loopback (LAN) access.

The application can be started with ``--host 0.0.0.0`` or with a concrete LAN
IPv4 address.  In that state every request that does not come from the machine
itself must first present a PIN that is generated at startup and shown on the
console.  Binding a loopback address keeps the historical behaviour: no PIN,
no session cookie, no change to any response.

The PIN has exactly two exits: the console (``print``) and, when every
condition in :func:`LanAuthState.local_pin_response` holds, one loopback-only
JSON endpoint.  It is never logged, never written to a file, never stored in
the session and never rendered into a page.

The module is wired from ``app.py`` through :func:`install`, which returns the
installed :class:`LanAuthState`.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import threading
import time

from flask import Response, jsonify, redirect, request, session

# --- Decision values (fixed; see the task sheet) ---------------------------
PIN_LENGTH = 6
SESSION_TTL_SECONDS = 12 * 60 * 60

PER_IP_FAILURE_LIMIT = 5
PER_IP_LOCKOUT_SECONDS = 5 * 60
GLOBAL_FAILURE_LIMIT = 20
GLOBAL_COOLDOWN_BASE_SECONDS = 5 * 60
GLOBAL_COOLDOWN_MAX_SECONDS = 60 * 60

# The PIN form only carries a handful of short fields.  The global request cap
# is roughly 2 GiB and Flask 3.0.3 cannot lower it for a single request, so the
# PIN submission is size checked before the body is parsed at all.
PIN_BODY_MAX_BYTES = 1024

PIN_PAGE_PATH = "/lan-pin"
LOCAL_PIN_API_PATH = "/api/local-pin"
UNAUTHORIZED_CODE = "lan_pin_required"

# Startup exits with 2 (backend override conflict) and 3 (no usable backend)
# already; an unsupported bind address uses a code of its own.
BIND_HOST_REJECTED_EXIT_CODE = 4

MODE_LOOPBACK = "loopback"
MODE_LAN = "lan"
MODE_UNSUPPORTED = "unsupported"

RESULT_OK = "ok"
RESULT_WRONG = "wrong"
RESULT_LOCKED = "locked"
RESULT_COOLING_DOWN = "cooling_down"

_PRUNE_THRESHOLD = 256
_PRUNE_FLOOR = 64

_LOOPBACK_V6 = ipaddress.IPv6Address("::1")

_PIN_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Enter PIN | 输入 PIN</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #14161c;
    color: #f2f4f8;
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  }
  .card {
    width: 100%;
    max-width: 420px;
    margin: 24px;
    padding: 28px;
    border: 1px solid #2c3140;
    border-radius: 14px;
    background: #1b1e26;
  }
  h1 { margin: 0 0 8px; font-size: 20px; }
  p.lead { margin: 0 0 18px; font-size: 13px; line-height: 1.6; color: #a8b0c0; }
  label { display: block; margin-bottom: 8px; font-size: 13px; color: #c8cfdd; }
  input {
    width: 100%;
    padding: 12px 14px;
    font-size: 20px;
    letter-spacing: 6px;
    text-align: center;
    color: #f2f4f8;
    background: #101219;
    border: 1px solid #384054;
    border-radius: 10px;
  }
  button {
    width: 100%;
    margin-top: 16px;
    padding: 12px;
    font-size: 15px;
    color: #14161c;
    background: #d4a373;
    border: 0;
    border-radius: 10px;
    cursor: pointer;
  }
  .error {
    margin-top: 16px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.5;
    color: #ffd7d7;
    background: #4a2027;
    border: 1px solid #7a2f39;
    border-radius: 8px;
  }
  .hint { margin-top: 18px; font-size: 12px; line-height: 1.6; color: #7f879a; }
</style>
</head>
<body>
  <div class="card">
    <h1>Enter the LAN access PIN / 请输入局域网访问 PIN</h1>
    <p class="lead">
      This app is reachable from other devices on this network, so it asks for
      the one-time PIN shown in the console window of the computer running it.<br>
      本程序已对局域网开放，请输入运行它的那台电脑控制台上显示的一次性 PIN。
    </p>
    <form method="post" action="__PIN_PAGE_PATH__" autocomplete="off">
      <label for="pin">PIN / 一次性 PIN</label>
      <input id="pin" name="pin" type="password" inputmode="numeric"
             autocomplete="off" maxlength="32" autofocus>
      <button type="submit">Unlock / 解锁</button>
    </form>
__ERROR_BLOCK__
    <p class="hint">
      The PIN is generated at every startup and is never stored in a log or a
      file.<br>
      PIN 每次启动重新生成，不会写入任何日志或文件。
    </p>
  </div>
</body>
</html>
"""

_ERROR_BLOCK_TEMPLATE = """    <div class="error">
      That PIN was not accepted, or access is temporarily locked after too many
      failed attempts. Please wait and try again.<br>
      PIN 未被接受，或失败次数过多已临时锁定。请稍后再试。
    </div>
"""


def classify_bind_host(value) -> str:
    """Return ``MODE_LOOPBACK``, ``MODE_LAN`` or ``MODE_UNSUPPORTED``.

    Only three kinds of bind address are supported: a loopback address
    (``127.0.0.0/8``, ``::1``, ``localhost``), ``0.0.0.0`` and a concrete IPv4
    literal.  Non-loopback IPv6 and host names are rejected because the request
    checks cannot decide which ``Host`` value to trust for them.
    """
    text = (value or "").strip()
    if not text:
        return MODE_UNSUPPORTED
    if text.lower() == "localhost":
        return MODE_LOOPBACK
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return MODE_UNSUPPORTED

    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            address = mapped
        elif address == _LOOPBACK_V6:
            return MODE_LOOPBACK
        else:
            return MODE_UNSUPPORTED

    if address.is_loopback:
        return MODE_LOOPBACK
    return MODE_LAN


def is_loopback_address(value) -> bool:
    """True when *value* is a loopback literal or ``localhost``."""
    return classify_bind_host(value) == MODE_LOOPBACK


def reject_unsupported_bind_host(bind_host, logger=None) -> None:
    """Exit with :data:`BIND_HOST_REJECTED_EXIT_CODE` for unsupported binds.

    English goes through the logger (console + ``app.log``), Chinese only
    through ``print`` so that ``app.log`` stays ASCII-safe.  Neither one ever
    carries a secret.
    """
    if classify_bind_host(bind_host) != MODE_UNSUPPORTED:
        return

    value = (bind_host or "").strip()
    english = [
        "=" * 60,
        "Unsupported bind address: %s" % value,
        "Only these bind addresses are supported:",
        "  - loopback: 127.0.0.0/8, ::1, localhost",
        "  - all IPv4 interfaces: 0.0.0.0",
        "  - one concrete IPv4 address, e.g. 192.168.1.23",
        "Non-loopback IPv6 addresses and host names are refused because the",
        "request checks cannot decide which Host header to trust for them.",
        "=" * 60,
    ]
    chinese = [
        "不支持的绑定地址：%s" % value,
        "仅支持以下绑定地址：",
        "  - 回环地址：127.0.0.0/8、::1、localhost",
        "  - 全部 IPv4 网卡：0.0.0.0",
        "  - 一个具体 IPv4 地址，例如 192.168.1.23",
        "非回环 IPv6 地址与主机名会被拒绝，因为无法判断应当信任哪个 Host 头。",
    ]
    emit = logger.error if logger is not None else print
    for line in english:
        emit(line)
    for line in chinese:
        print(line)

    raise SystemExit(BIND_HOST_REJECTED_EXIT_CODE)


def _json_error(status: int, message: str):
    return jsonify({"error": message}), status


def compare_pin(candidate, pin) -> bool:
    """Compare a submitted PIN with the generated one, byte by byte.

    ``hmac.compare_digest`` refuses two ``str`` operands that contain
    non-ASCII characters and raises ``TypeError``. Anyone on the network could
    therefore turn a full-width digit or a Chinese character into a 500 and a
    traceback in ``app.log``, without ever spending a failed attempt. Encoding
    both sides first makes every input an ordinary wrong PIN, which is what the
    form should treat it as. No normalisation is done: full-width digits are a
    different string on purpose.
    """
    if not isinstance(candidate, str):
        return False
    try:
        candidate_bytes = candidate.encode("utf-8")
    except UnicodeEncodeError:  # lone surrogates, e.g. from a broken client
        return False
    return hmac.compare_digest(candidate_bytes, pin.encode("ascii"))


def _split_host(value):
    """Split a ``Host`` header into ``(hostname, port_text)``.

    Returns ``None`` when the header is missing or malformed.  IPv6 literals
    must be written the standard way, in square brackets.
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        hostname = text[1:end]
        rest = text[end + 1:]
        if rest:
            if not rest.startswith(":"):
                return None
            port_text = rest[1:]
        else:
            port_text = ""
    elif ":" in text:
        hostname, _, port_text = text.rpartition(":")
    else:
        hostname, port_text = text, ""
    if not hostname:
        return None
    return hostname, port_text


def _host_as_ip(hostname):
    """Return an IPv4Address/IPv6Address, or ``None`` for a name."""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            return mapped
        return address
    return address


def host_is_allowed(host_header, bind_host, port) -> bool:
    """Host header check (D6), applied in both loopback and LAN mode.

    The port has to be the one we bound, and every name is refused except
    ``localhost``: DNS rebinding has to bring its own domain name with it, so
    accepting only IP literals (plus the loopback name) removes the whole
    attack.  Enumerating the machine's own addresses would be fragile instead
    (multiple NICs, virtual adapters, DHCP changes), so binding
    0.0.0.0 accepts any IPv4 literal and binding a concrete IP accepts that IP.
    """
    parsed = _split_host(host_header)
    if parsed is None:
        return False
    hostname, port_text = parsed
    if port_text != str(port):
        return False

    lowered = hostname.lower()
    if lowered == "localhost":
        return True

    address = _host_as_ip(lowered)
    if address is None:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        return address == _LOOPBACK_V6
    if address.is_loopback:
        return True

    bind_mode = classify_bind_host(bind_host)
    if bind_mode == MODE_LOOPBACK:
        return False
    bind_address = _host_as_ip((bind_host or "").strip())
    if bind_address is None or str(bind_address) == "0.0.0.0":
        return True
    return address == bind_address


def _is_navigation_request() -> bool:
    """True for a top-level navigation (missing header falls back to Accept)."""
    mode = request.headers.get("Sec-Fetch-Mode")
    if mode is not None:
        return mode.strip().lower() == "navigate"
    accept = request.headers.get("Accept") or ""
    return "text/html" in accept.lower()


class _IpRecord:
    __slots__ = ("failures", "locked_until")

    def __init__(self):
        self.failures = 0
        self.locked_until = 0.0


class _FailureLimiter:
    """Per-IP lockout plus a process-wide cooldown with a doubling level.

    Everything that matters for correctness happens inside one critical
    section: "am I locked / cooling down" -> "compare the PIN" -> "update the
    counters".  Splitting those steps across lock releases would let concurrent
    requests squeeze extra guesses past the thresholds.
    """

    def __init__(self, clock, on_global_cooldown=None):
        self._clock = clock
        self._on_global_cooldown = on_global_cooldown
        self._lock = threading.Lock()
        self._records = {}
        self._global_failures = 0
        self._global_cooldown_until = 0.0
        self._cooldown_level = 0

    @property
    def global_failures(self) -> int:
        return self._global_failures

    @property
    def cooldown_level(self) -> int:
        return self._cooldown_level

    def failures_for(self, source) -> int:
        """Failed attempts recorded for *source* (0 when unknown/expired)."""
        now = self._clock()
        with self._lock:
            record = self._records.get(source)
            if record is None:
                return 0
            if record.locked_until and record.locked_until <= now:
                return 0
            return record.failures

    def is_locked(self, source) -> bool:
        now = self._clock()
        with self._lock:
            record = self._records.get(source)
            return record is not None and record.locked_until > now

    def is_cooling_down(self) -> bool:
        return self._global_cooldown_until > self._clock()

    def cooldown_remaining(self) -> float:
        return max(0.0, self._global_cooldown_until - self._clock())

    def submit(self, source, candidate, pin, compare) -> str:
        """Compare *candidate* against *pin* and book the outcome atomically."""
        with self._lock:
            now = self._clock()
            if self._global_cooldown_until and self._global_cooldown_until <= now:
                # Cooldown expired: the global count restarts, the doubling
                # level is deliberately kept.
                self._global_failures = 0
                self._global_cooldown_until = 0.0
            if self._global_cooldown_until > now:
                return RESULT_COOLING_DOWN

            record = self._records.get(source)
            if record is not None:
                if record.locked_until > now:
                    return RESULT_LOCKED
                if record.locked_until:
                    # Lockout expired: this IP starts from zero again.
                    record.failures = 0
                    record.locked_until = 0.0

            if compare(candidate, pin):
                if record is not None:
                    record.failures = 0
                    record.locked_until = 0.0
                self._prune(now)
                return RESULT_OK

            if record is None:
                record = _IpRecord()
                self._records[source] = record
            record.failures += 1
            if record.failures >= PER_IP_FAILURE_LIMIT:
                record.locked_until = now + PER_IP_LOCKOUT_SECONDS

            self._global_failures += 1
            if self._global_failures >= GLOBAL_FAILURE_LIMIT:
                seconds = min(
                    GLOBAL_COOLDOWN_BASE_SECONDS * (2 ** self._cooldown_level),
                    GLOBAL_COOLDOWN_MAX_SECONDS,
                )
                self._global_cooldown_until = now + seconds
                self._cooldown_level += 1
                if self._on_global_cooldown is not None:
                    self._on_global_cooldown(seconds)

            self._prune(now)
            return RESULT_WRONG

    def _prune(self, now) -> None:
        """Keep memory bounded; only records with nothing left are dropped."""
        if len(self._records) < _PRUNE_THRESHOLD:
            return
        stale = [
            key
            for key, record in self._records.items()
            if record.failures == 0 and record.locked_until <= now
        ]
        if len(self._records) - len(stale) < _PRUNE_FLOOR:
            return
        for key in stale:
            del self._records[key]


class LanAuthState:
    """Everything the gate needs for one process (one startup)."""

    def __init__(self, bind_host, port, clock=None):
        self.bind_host = (bind_host or "").strip()
        self.port = int(port)
        self.mode = classify_bind_host(self.bind_host)
        self.enabled = self.mode == MODE_LAN
        self.clock = clock or time.time
        self.pin = None
        # Binding a concrete LAN IP means 127.0.0.1 is not listening, so the
        # loopback exemptions (D2 and D5) cannot apply.
        self.loopback_reachable = self.enabled and self.bind_host == "0.0.0.0"
        self.limiter = _FailureLimiter(self.clock, self._announce_global_cooldown)

    # --- wiring ---------------------------------------------------------
    def install(self, app) -> None:
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
        app.config["SESSION_PERMANENT"] = False

        if self.enabled:
            # Both are regenerated on every start, so a restart invalidates
            # every session issued before it.
            app.secret_key = secrets.token_bytes(32)
            self.pin = "".join(
                secrets.choice("0123456789") for _ in range(PIN_LENGTH)
            )
            app.add_url_rule(
                PIN_PAGE_PATH, "lan_pin", self.pin_page, methods=["GET", "POST"]
            )

        app.before_request(self._before_request)

    def announce_pin(self) -> None:
        """Print the PIN on the console.  The only place it is ever shown."""
        if not self.enabled:
            return
        separator = "=" * 60
        print(separator)
        print("LAN access is enabled. One-time PIN / 局域网访问一次性 PIN:")
        print("    %s" % self.pin)
        print("Enter it on the other device to open the app.")
        print("在其他设备上输入此 PIN 以打开本程序。")
        print("The PIN changes on every restart and is never written to a log.")
        print("PIN 每次启动都会改变，且不会写入任何日志。")
        print(separator)

    def _announce_global_cooldown(self, seconds) -> None:
        minutes = max(1, int(round(seconds / 60.0)))
        print(
            "[LAN PIN] Too many failed attempts; new devices are locked out for "
            "about %d minute(s). Already signed-in sessions keep working."
            % minutes
        )
        print(
            "[局域网 PIN] 失败次数过多，新设备将在约 %d 分钟内无法登录；已登录的会话不受影响。"
            % minutes
        )

    # --- request gate ---------------------------------------------------
    def _before_request(self):
        # 1. Host header check first: a rebinding page must never be able to
        # reach the PIN page and submit to it.
        if not host_is_allowed(request.headers.get("Host"), self.bind_host, self.port):
            return Response("Invalid Host header.", status=400, mimetype="text/plain")

        # 1a. The loopback-only PIN readout. It is answered here, before the
        # PIN page, D2 and the session check, so it can never answer 401 and
        # never redirect: a phone gets a plain 404 either way.
        if request.path == LOCAL_PIN_API_PATH:
            return self.local_pin_response()

        # 2. Cross-site check on state-changing methods (D7), in both modes.
        # It is what makes the loopback exemption in step 4 safe: without it,
        # any web page could make the visitor's own browser POST to
        # 127.0.0.1. It also closes the same hole in the default local-only
        # mode, where three endpoints take no JSON body at all.
        rejection = self._cross_site_rejection()
        if rejection is not None:
            return rejection

        if not self.enabled:
            return None

        # 3. The PIN page is the only unauthenticated entry point.
        if request.path == PIN_PAGE_PATH:
            if request.method == "POST":
                return self._reject_unusable_pin_body()
            return None

        # 4. Loopback callers keep working without a PIN (D2).
        if self.loopback_reachable and is_loopback_address(request.remote_addr):
            return None

        # 5. A session is only valid until the server restarts or the TTL runs
        # out; the check is server-side so a sliding cookie cannot extend it.
        if self._session_is_valid():
            return None

        # 6. Everything else is unauthenticated.
        return self._unauthenticated_response()

    def _cross_site_rejection(self):
        """403 for state-changing requests that did not come from our own page.

        ``Sec-Fetch-Site`` wins when present; otherwise ``Origin`` has to match
        the request's own Host exactly. A client that sends neither is not a
        browser and is let through.
        """
        if request.method.upper() in ("GET", "HEAD", "OPTIONS"):
            return None

        message = "Cross-site requests are not allowed."
        site = request.headers.get("Sec-Fetch-Site")
        if site is not None:
            if site.strip().lower() != "same-origin":
                return _json_error(403, message)
            return None

        origin = request.headers.get("Origin")
        if origin is not None and origin.strip() != "http://" + request.host:
            return _json_error(403, message)
        return None

    def _reject_unusable_pin_body(self):
        """Check the submission before the body is parsed (see module docs)."""
        length = request.content_length
        if length is None:
            return Response(
                "Content-Length is required.", status=411, mimetype="text/plain"
            )
        if length > PIN_BODY_MAX_BYTES:
            return Response(
                "PIN submission is too large.", status=413, mimetype="text/plain"
            )
        if request.mimetype != "application/x-www-form-urlencoded":
            return Response(
                "Expected a URL-encoded form.", status=415, mimetype="text/plain"
            )
        return None

    def local_pin_response(self):
        """D5: the PIN for the machine's own browser, or a plain 404.

        Everything that is not exactly "LAN mode, bound to all interfaces so
        that 127.0.0.1 is reachable, GET, caller is loopback, same origin" gets
        the same 404 an unknown path would get.
        """
        if (
            self.enabled
            and self.loopback_reachable
            and request.method == "GET"
            and is_loopback_address(request.remote_addr)
        ):
            site = request.headers.get("Sec-Fetch-Site")
            if site is None or site.strip().lower() == "same-origin":
                response = jsonify({"pin": self.pin})
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
                return response
        return Response("Not Found", status=404, mimetype="text/plain")

    def _session_is_valid(self) -> bool:
        if not session.get("lan_pin_authenticated"):
            return False
        logged_in_at = session.get("lan_pin_login_at")
        if not isinstance(logged_in_at, (int, float)):
            session.clear()
            return False
        if self.clock() - logged_in_at > SESSION_TTL_SECONDS:
            session.clear()
            return False
        return True

    def _unauthenticated_response(self):
        if _is_navigation_request():
            # No `next` parameter: after unlocking, everyone lands on "/".
            return redirect(PIN_PAGE_PATH, code=302)
        return (
            jsonify(
                {
                    "error": "LAN access PIN required.",
                    "code": UNAUTHORIZED_CODE,
                    "pin_page": PIN_PAGE_PATH,
                }
            ),
            401,
        )

    # --- PIN page -------------------------------------------------------
    def pin_page(self):
        if request.method == "POST":
            return self._handle_pin_submission()
        return self._render_pin_page(error=False)

    def _handle_pin_submission(self):
        candidate = request.form.get("pin", "")
        outcome = self.limiter.submit(
            request.remote_addr or "", candidate, self.pin, compare_pin
        )
        if outcome == RESULT_OK:
            session.clear()
            session.permanent = False
            session["lan_pin_authenticated"] = True
            session["lan_pin_login_at"] = self.clock()
            return redirect("/", code=302)
        return self._render_pin_page(error=True)

    def _render_pin_page(self, error):
        html = _PIN_PAGE_TEMPLATE.replace("__PIN_PAGE_PATH__", PIN_PAGE_PATH)
        html = html.replace("__ERROR_BLOCK__", _ERROR_BLOCK_TEMPLATE if error else "")
        response = Response(html, mimetype="text/html")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response


def install(app, bind_host, port, clock=None) -> LanAuthState:
    """Wire the LAN PIN gate into *app* and return its state."""
    state = LanAuthState(bind_host, port, clock=clock)
    state.install(app)
    app.extensions["lan_auth"] = state
    return state
