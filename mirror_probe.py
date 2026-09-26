"""Rank pip package mirrors by a short measured download.

Run as its own process by run_portable.ps1 right before pip is used, at most
once per launch. It downloads the first megabyte of the same pinned numpy
wheel from every candidate and prints one line per candidate plus one
machine-readable ranking line for the launcher.

Standard library only, and no certificate checks are disabled anywhere.

Reading is capped by design. The socket timeout only bounds how long a single
blocking operation waits for data; a server that dribbles one byte at a time
would keep a plain read(n) alive indefinitely. The loop therefore issues at
most one underlying read per call (HTTPResponse.read1) and re-checks a
monotonic clock after every return, against both a per-source deadline and a
global one. The workers are daemon threads and the main thread never joins
them, so the process leaves at the global deadline no matter how slow a read
would be; the launcher adds a process-level timeout on top of that.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

PROBE_BYTES = 1024 * 1024
RANGE_HEADER = "bytes=0-%d" % (PROBE_BYTES - 1)
SOCKET_TIMEOUT_SECONDS = 2.0
PER_SOURCE_DEADLINE_SECONDS = 8.0
GLOBAL_DEADLINE_SECONDS = 10.0
READ_CHUNK_BYTES = 64 * 1024
POLL_SECONDS = 0.02

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_CONN = "conn"
STATUS_TLS = "tls"
STATUS_SHORT_READ = "short_read"

LINE_PREFIX = "[mirror-probe]"
RANK_MARKER = "rank"

# Every candidate serves the same file, and the four mirrors keep PyPI's
# package layout, so one path suffix works for all of them. requirements.txt
# pins the version; a test fails when that pin changes, which is the reminder
# to update this path with it.
PROBE_WHEEL = "numpy-1.26.4-cp312-cp312-win_amd64.whl"
PROBE_WHEEL_PATH = (
    "16/2e/86f24451c2d530c88daf997cb8d6ac622c1d40d19f5a031ed68a4b73a374/"
    + PROBE_WHEEL
)


@dataclass(frozen=True)
class Candidate:
    name: str
    index_url: str
    probe_url: str


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: str
    seconds: float | None = None


DEFAULT_CANDIDATES = (
    Candidate(
        "aliyun",
        "https://mirrors.aliyun.com/pypi/simple/",
        "https://mirrors.aliyun.com/pypi/packages/" + PROBE_WHEEL_PATH,
    ),
    Candidate(
        "tuna",
        "https://pypi.tuna.tsinghua.edu.cn/simple/",
        "https://pypi.tuna.tsinghua.edu.cn/packages/" + PROBE_WHEEL_PATH,
    ),
    Candidate(
        "tencent",
        "https://mirrors.cloud.tencent.com/pypi/simple/",
        "https://mirrors.cloud.tencent.com/pypi/packages/" + PROBE_WHEEL_PATH,
    ),
    Candidate(
        "huawei",
        "https://repo.huaweicloud.com/repository/pypi/simple/",
        "https://repo.huaweicloud.com/repository/pypi/packages/" + PROBE_WHEEL_PATH,
    ),
    Candidate(
        "pypi",
        "https://pypi.org/simple/",
        "https://files.pythonhosted.org/packages/" + PROBE_WHEEL_PATH,
    ),
)

_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_name(name: str) -> str:
    """Keep the short name usable as a token in the rank line."""
    return _NAME_PATTERN.sub("_", str(name))


def _status_from_url_error(error: urllib.error.URLError) -> str:
    reason = error.reason
    if isinstance(reason, ssl.SSLError):
        return STATUS_TLS
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return STATUS_TIMEOUT
    return STATUS_CONN


def _probe_candidate(
    candidate: Candidate,
    *,
    read_bytes: int,
    socket_timeout: float,
    per_source_deadline_epoch: float,
    global_deadline_epoch: float,
) -> ProbeResult:
    """Download up to *read_bytes*, timed from the request to the last byte."""
    name = _safe_name(candidate.name)
    started = time.monotonic()
    request = urllib.request.Request(
        candidate.probe_url,
        headers={"Range": RANGE_HEADER, "User-Agent": "bashi-mirror-probe/1.0"},
    )
    response = None
    try:
        response = urllib.request.urlopen(request, timeout=socket_timeout)
    except urllib.error.HTTPError as error:
        return ProbeResult(name, "http_%d" % error.code)
    except urllib.error.URLError as error:
        return ProbeResult(name, _status_from_url_error(error))
    except ssl.SSLError:
        return ProbeResult(name, STATUS_TLS)
    except (TimeoutError, socket.timeout):
        return ProbeResult(name, STATUS_TIMEOUT)
    except OSError:
        return ProbeResult(name, STATUS_CONN)

    deadline = min(per_source_deadline_epoch, global_deadline_epoch)
    total = 0
    try:
        while total < read_bytes:
            if time.monotonic() >= deadline:
                return ProbeResult(name, STATUS_TIMEOUT)
            chunk = response.read1(min(READ_CHUNK_BYTES, read_bytes - total))
            if not chunk:
                break
            total += len(chunk)
            if time.monotonic() >= deadline:
                return ProbeResult(name, STATUS_TIMEOUT)
        if total < read_bytes:
            return ProbeResult(name, STATUS_SHORT_READ)
        return ProbeResult(name, STATUS_OK, time.monotonic() - started)
    except http.client.IncompleteRead:
        return ProbeResult(name, STATUS_SHORT_READ)
    except (TimeoutError, socket.timeout):
        return ProbeResult(name, STATUS_TIMEOUT)
    except ssl.SSLError:
        return ProbeResult(name, STATUS_TLS)
    except (http.client.HTTPException, OSError):
        return ProbeResult(name, STATUS_CONN)
    finally:
        if response is not None:
            try:
                response.close()
            except OSError:
                pass


def probe_candidates(
    candidates,
    *,
    read_bytes: int = PROBE_BYTES,
    socket_timeout: float = SOCKET_TIMEOUT_SECONDS,
    per_source_deadline: float = PER_SOURCE_DEADLINE_SECONDS,
    global_deadline: float = GLOBAL_DEADLINE_SECONDS,
):
    """Probe every candidate in parallel and return one result per candidate.

    Returns at the global deadline even when a worker is still reading; that
    worker is a daemon thread and its candidate is recorded as a timeout.
    """
    started = time.monotonic()
    per_source_deadline_epoch = started + per_source_deadline
    global_deadline_epoch = started + global_deadline
    results = [None] * len(candidates)

    def run(index, candidate):
        results[index] = _probe_candidate(
            candidate,
            read_bytes=read_bytes,
            socket_timeout=socket_timeout,
            per_source_deadline_epoch=per_source_deadline_epoch,
            global_deadline_epoch=global_deadline_epoch,
        )

    for index, candidate in enumerate(candidates):
        thread = threading.Thread(
            target=run,
            args=(index, candidate),
            name="mirror-probe-%s" % _safe_name(candidate.name),
            daemon=True,
        )
        thread.start()

    while time.monotonic() < global_deadline_epoch:
        if all(result is not None for result in results):
            break
        time.sleep(POLL_SECONDS)

    return [
        results[index]
        if results[index] is not None
        else ProbeResult(_safe_name(candidate.name), STATUS_TIMEOUT)
        for index, candidate in enumerate(candidates)
    ]


def rank_results(results):
    """Fastest success first, then the failures in their original order."""
    succeeded = sorted(
        (result for result in results if result.status == STATUS_OK),
        key=lambda result: result.seconds if result.seconds is not None else 0.0,
    )
    failed = [result for result in results if result.status != STATUS_OK]
    return succeeded + failed


def format_result_line(result: ProbeResult) -> str:
    if result.status == STATUS_OK and result.seconds is not None:
        return "%s %s %s %.2fs" % (LINE_PREFIX, result.name, STATUS_OK, result.seconds)
    return "%s %s %s" % (LINE_PREFIX, result.name, result.status)


def format_rank_line(ranked) -> str:
    return "%s %s %s" % (
        LINE_PREFIX,
        RANK_MARKER,
        ",".join(result.name for result in ranked),
    )


def load_candidates(path: str):
    """Candidate list from JSON; used by the tests to point at local servers."""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return tuple(
        Candidate(str(entry["name"]), str(entry["index_url"]), str(entry["probe_url"]))
        for entry in payload
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Short download test against the configured pip mirrors."
    )
    parser.add_argument("--read-bytes", type=int, default=PROBE_BYTES)
    parser.add_argument("--socket-timeout", type=float, default=SOCKET_TIMEOUT_SECONDS)
    parser.add_argument(
        "--per-source-deadline", type=float, default=PER_SOURCE_DEADLINE_SECONDS
    )
    parser.add_argument("--global-deadline", type=float, default=GLOBAL_DEADLINE_SECONDS)
    parser.add_argument(
        "--candidates-json",
        default="",
        help="JSON file with name/index_url/probe_url entries (testing).",
    )
    args = parser.parse_args(argv)

    candidates = DEFAULT_CANDIDATES
    if args.candidates_json:
        candidates = load_candidates(args.candidates_json)

    results = probe_candidates(
        candidates,
        read_bytes=args.read_bytes,
        socket_timeout=args.socket_timeout,
        per_source_deadline=args.per_source_deadline,
        global_deadline=args.global_deadline,
    )
    ranked = rank_results(results)

    for result in ranked:
        print(format_result_line(result), flush=True)
    print(format_rank_line(ranked), flush=True)

    if any(result.status == STATUS_OK for result in results):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
