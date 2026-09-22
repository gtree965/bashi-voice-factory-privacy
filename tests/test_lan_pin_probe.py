"""Runs the front-end PIN probe under node's ``vm`` with a fake clock.

The probe exists because a restarted app answers with a network error rather
than a 401, and its whole reason to exist is the 300-second deadline. A test
that waits 300 real seconds is not usable, so the block is written as a factory
with every dependency injected and is loaded here verbatim out of ``app.js``.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
APP_JS = APP_ROOT / "static" / "js" / "app.js"

BLOCK_BEGIN = "// --- BEGIN LAN PIN frontend block"
BLOCK_END = "// --- END LAN PIN frontend block"

FALLBACK_NODE_PATHS = (Path(r"C:\Program Files\nodejs\node.exe"),)

SCENARIO_LINES = (
    "passed: 401 inside the deadline moves the page",
    "passed: a server that recovers at second 301 changes nothing",
    "passed: an answer that arrives after the deadline is ignored",
    "passed: no request is sent after the deadline",
)

HARNESS_JS = r"""
'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const blockPath = process.argv[2];
const blockSource = fs.readFileSync(blockPath, 'utf8');

const sandbox = {
    console: console,
    Promise: Promise,
    window: {
        fetch: function () {
            return Promise.reject(new Error('the raw fetch has to be injected'));
        },
        location: { pathname: '/', href: '' },
        setTimeout: setTimeout,
        clearTimeout: clearTimeout
    }
};
vm.createContext(sandbox);
vm.runInContext(blockSource, sandbox, { filename: 'app.js LAN PIN block' });

const createLanPinProbe = sandbox.createLanPinProbe;
assert.strictEqual(
    typeof createLanPinProbe,
    'function',
    'createLanPinProbe is missing from the extracted block'
);

const tick = function () {
    return new Promise(function (resolve) { setImmediate(resolve); });
};

const INTERVAL_MS = 3000;
const TIMEOUT_MS = 300000;

function makeEnv(overrides) {
    const clock = { now: 0 };
    const timers = [];
    let nextTimerId = 1;

    function setTimeoutFake(fn, ms) {
        const id = nextTimerId++;
        timers.push({ id: id, at: clock.now + ms, order: id, fn: fn });
        return id;
    }

    function clearTimeoutFake(id) {
        const index = timers.findIndex(function (timer) { return timer.id === id; });
        if (index >= 0) {
            timers.splice(index, 1);
        }
    }

    function fireNext() {
        if (timers.length === 0) {
            return false;
        }
        timers.sort(function (a, b) { return (a.at - b.at) || (a.order - b.order); });
        const timer = timers.shift();
        clock.now = Math.max(clock.now, timer.at);
        timer.fn();
        return true;
    }

    const requests = [];
    function fetchFake(url, init) {
        const entry = { url: url, at: clock.now, signal: init && init.signal, settled: false };
        entry.promise = new Promise(function (resolve, reject) {
            entry.resolve = function (value) { entry.settled = true; resolve(value); };
            entry.reject = function (value) { entry.settled = true; reject(value); };
        });
        requests.push(entry);
        return entry.promise;
    }

    const navigations = [];
    const aborts = [];
    function createAbortController() {
        return {
            aborted: false,
            signal: { aborted: false },
            abort: function () {
                if (this.aborted) {
                    return;
                }
                this.aborted = true;
                this.signal.aborted = true;
                aborts.push(clock.now);
                const signal = this.signal;
                // A real fetch rejects whatever was still on the wire.
                requests.forEach(function (entry) {
                    if (!entry.settled && entry.signal === signal) {
                        entry.reject(new Error('aborted'));
                    }
                });
            }
        };
    }

    const settings = Object.assign({
        now: function () { return clock.now; },
        setTimeout: setTimeoutFake,
        clearTimeout: clearTimeoutFake,
        fetch: fetchFake,
        navigate: function () { navigations.push(clock.now); },
        createAbortController: createAbortController,
        intervalMs: INTERVAL_MS,
        timeoutMs: TIMEOUT_MS
    }, overrides || {});

    return {
        clock: clock,
        fireNext: fireNext,
        requests: requests,
        navigations: navigations,
        aborts: aborts,
        probe: createLanPinProbe(settings)
    };
}

function latestInFlight(env) {
    const pending = env.requests.filter(function (entry) { return !entry.settled; });
    return pending.length === 0 ? null : pending[pending.length - 1];
}

function response401() {
    return {
        status: 401,
        json: function () { return Promise.resolve({ code: 'lan_pin_required' }); }
    };
}

async function scenarioJumpInsideTheDeadline() {
    const env = makeEnv({});
    env.probe.start();
    for (let i = 0; i < 100 && !latestInFlight(env); i++) {
        assert.ok(env.fireNext(), 'no retry timer was scheduled');
        await tick();
    }
    const entry = latestInFlight(env);
    assert.ok(entry, 'no request was ever sent');
    env.clock.now = 299000;
    entry.resolve(response401());
    await tick();
    assert.deepStrictEqual(env.navigations, [299000], 'the page should move at second 299');
    assert.strictEqual(env.probe.isRunning(), false, 'the probe should have stopped');
}

async function scenarioRecoveryAfterTheDeadline() {
    const env = makeEnv({});
    env.probe.start();
    let guard = 0;
    while (env.clock.now < 297000) {
        guard += 1;
        assert.ok(guard < 5000, 'never reached second 297');
        const entry = latestInFlight(env);
        if (entry) {
            entry.reject(new Error('server down'));
            await tick();
            continue;
        }
        assert.ok(env.fireNext(), 'no retry timer was scheduled');
        await tick();
    }
    const hung = latestInFlight(env);
    assert.ok(hung && hung.at === 297000, 'expected one request in flight at second 297');
    assert.ok(env.requests.length >= 2, 'the probe should have retried at least once');

    // Only the deadline timer is left now, and it aborts the request that is
    // still on the wire instead of leaving it to the browser.
    assert.ok(env.fireNext(), 'the deadline timer was not scheduled');
    await tick();
    assert.deepStrictEqual(env.aborts, [300000], 'nothing was aborted at the deadline');
    assert.strictEqual(hung.settled, true, 'the hung request was not aborted');
    assert.strictEqual(env.probe.isRunning(), false, 'the probe should have stopped');
    env.requests.forEach(function (entry) {
        assert.ok(
            entry.at < TIMEOUT_MS,
            'a request went out at or after the deadline: ' + entry.at
        );
    });

    // From second 301 on, a restarted server would answer 401. It must never
    // get the chance, and the late page must stay where it is.
    env.clock.now = 301000;
    const made = env.requests.length;
    while (env.fireNext()) {
        await tick();
    }
    assert.strictEqual(env.requests.length, made, 'a request was made after the deadline');
    assert.deepStrictEqual(env.navigations, [], 'the page must not move after the deadline');
}

async function scenarioAnswerAfterTheDeadline() {
    const env = makeEnv({ intervalMs: 2000 });
    env.probe.start();
    let entry = null;
    let guard = 0;
    while (!entry) {
        guard += 1;
        assert.ok(guard < 5000, 'never reached second 298');
        const pending = latestInFlight(env);
        if (pending) {
            pending.reject(new Error('server down'));
            await tick();
            continue;
        }
        assert.ok(env.fireNext(), 'no retry timer was scheduled');
        await tick();
        const started = latestInFlight(env);
        if (started && started.at === 298000) {
            entry = started;
        }
    }
    env.clock.now = 301000;
    entry.resolve(response401());
    await tick();
    assert.deepStrictEqual(env.navigations, [], 'a late 401 must be ignored');
    assert.strictEqual(env.probe.isRunning(), false, 'the probe should have stopped');
}

async function scenarioNoRequestAfterTheDeadline() {
    const env = makeEnv({});
    env.probe.start();
    let guard = 0;
    while (env.probe.isRunning()) {
        guard += 1;
        assert.ok(guard < 5000, 'the probe never stopped');
        const entry = latestInFlight(env);
        if (entry) {
            entry.reject(new Error('server down'));
            await tick();
            continue;
        }
        assert.ok(env.fireNext(), 'the probe is running with no timer scheduled');
        await tick();
    }
    const made = env.requests.length;
    assert.ok(made > 1, 'the probe should have retried at least once');
    assert.strictEqual(
        env.requests[made - 1].at,
        297000,
        'the last request should be the one sent just before the deadline'
    );
    env.clock.now = 600000;
    while (env.fireNext()) {
        await tick();
    }
    assert.strictEqual(env.requests.length, made, 'a request went out after the deadline');
    assert.deepStrictEqual(env.navigations, []);
}

const scenarios = [
    ['401 inside the deadline moves the page', scenarioJumpInsideTheDeadline],
    ['a server that recovers at second 301 changes nothing', scenarioRecoveryAfterTheDeadline],
    ['an answer that arrives after the deadline is ignored', scenarioAnswerAfterTheDeadline],
    ['no request is sent after the deadline', scenarioNoRequestAfterTheDeadline]
];

(async function main() {
    for (let i = 0; i < scenarios.length; i++) {
        await scenarios[i][1]();
        console.log('passed: ' + scenarios[i][0]);
    }
})().catch(function (error) {
    console.error('FAILED: ' + (error && error.stack ? error.stack : error));
    process.exit(1);
});
"""


def _find_node():
    found = shutil.which("node")
    if found:
        return found
    for candidate in FALLBACK_NODE_PATHS:
        if candidate.exists():
            return str(candidate)
    return None


def _probe_block() -> str:
    """The code between the two marker lines, taken out of app.js unchanged."""
    source = APP_JS.read_text(encoding="utf-8")
    marker = source.index(BLOCK_BEGIN)
    start = source.index("\n", marker) + 1
    end = source.index(BLOCK_END)
    if end <= start:
        raise AssertionError("the LAN PIN block markers are out of order")
    return source[start:end]


class LanPinProbeTests(unittest.TestCase):
    def test_the_extracted_block_is_the_shipped_probe(self):
        block = _probe_block()

        for needle in (
            "createLanPinProbe",
            "bashiRawFetch(input, init)",
            "createAbortController",
            "LAN_PIN_PROBE_INTERVAL_MS",
            "LAN_PIN_PROBE_TIMEOUT_MS",
            "bashiStartPinProbe",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, block)
        # The wrapper must not be what the probe calls: a 401 there would move
        # the page unconditionally, without looking at the deadline.
        self.assertNotIn("window.fetch(", block)

    def test_the_deadline_cases_pass_under_node(self):
        node = _find_node()
        if node is None:
            self.skipTest(
                "node is not installed, so the deadline cases cannot run here; "
                "they are required on the machine that builds the candidate package"
            )

        with tempfile.TemporaryDirectory() as tmp:
            block_path = Path(tmp) / "lan_pin_block.js"
            block_path.write_text(_probe_block(), encoding="utf-8")
            harness_path = Path(tmp) / "harness.js"
            harness_path.write_text(HARNESS_JS, encoding="utf-8")
            result = subprocess.run(
                [node, str(harness_path), str(block_path)],
                capture_output=True,
                text=True,
                timeout=180,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        for line in SCENARIO_LINES:
            with self.subTest(scenario=line):
                self.assertIn(line, result.stdout)


if __name__ == "__main__":
    unittest.main()
