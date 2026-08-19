import inspect
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from flask import Flask

import tts_routes


class FakeWarmupService:
    def __init__(self):
        self.active = False
        self.fail = False
        self.mark_started_calls = 0
        self.mark_finished_calls = 0
        self.synthesis_calls = []

    def mark_warmup_started(self):
        self.active = True
        self.mark_started_calls += 1

    def mark_warmup_finished(self):
        self.active = False
        self.mark_finished_calls += 1

    def synthesize_text(self, text, voice):
        self.synthesis_calls.append((text, voice))
        if self.fail:
            raise RuntimeError("simulated warmup failure: 预热失败")
        return "warmup-test.mp3"


class ControlledExecutor:
    def __init__(self):
        self.submit_count = 0
        self.future = None
        self.task = None

    def submit(self, fn, *args, **kwargs):
        self.submit_count += 1
        self.future = Future()
        self.task = (fn, args, kwargs)
        return self.future

    def run(self):
        fn, args, kwargs = self.task
        self.future.set_running_or_notify_cancel()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            self.future.set_exception(exc)
        else:
            self.future.set_result(result)


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class WarmupRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(tts_routes.tts_bp)
        self.client = self.app.test_client()
        self.original_service = tts_routes.service
        self.original_executor = tts_routes._WARMUP_EXECUTOR
        self.original_future = tts_routes._WARMUP_FUTURE
        self.original_state = tts_routes._WARMUP_STATE
        self.info_patcher = patch.object(tts_routes.logger, "info")
        self.warning_patcher = patch.object(tts_routes.logger, "warning")
        self.info_mock = self.info_patcher.start()
        self.warning_mock = self.warning_patcher.start()
        self.service = FakeWarmupService()
        self.executor = ControlledExecutor()
        tts_routes.service = self.service
        tts_routes._WARMUP_EXECUTOR = self.executor
        tts_routes._WARMUP_FUTURE = None
        tts_routes._WARMUP_STATE = {
            "state": "cold",
            "started_at": None,
            "elapsed_seconds": None,
            "error": None,
        }

    def tearDown(self):
        if self.executor.future is not None and not self.executor.future.done():
            self.executor.future.cancel()
        tts_routes.service = self.original_service
        tts_routes._WARMUP_EXECUTOR = self.original_executor
        tts_routes._WARMUP_FUTURE = self.original_future
        tts_routes._WARMUP_STATE = self.original_state
        self.warning_patcher.stop()
        self.info_patcher.stop()

    def test_post_warmup_is_idempotent_while_task_is_pending(self):
        first = self.client.post("/api/warmup")
        second = self.client.post("/api/warmup")

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual("warming", second.get_json()["state"])
        self.assertEqual(1, self.executor.submit_count)
        self.assertEqual(1, self.service.mark_started_calls)

        self.executor.run()

    def test_warmup_status_reports_cold_warming_ready_and_failed(self):
        self.assertEqual("cold", self.client.get("/api/warmup/status").get_json()["state"])

        self.client.post("/api/warmup")
        warming = self.client.get("/api/warmup/status").get_json()
        self.assertEqual("warming", warming["state"])
        self.assertGreaterEqual(warming["elapsed_seconds"], 0)
        self.assertEqual(
            tts_routes.WARMUP_WAIT_TIMEOUT,
            warming["wait_timeout_seconds"],
        )

        self.executor.run()
        ready = self.client.get("/api/warmup/status").get_json()
        self.assertEqual("ready", ready["state"])
        self.assertIsNone(ready["error"])
        self.info_mock.assert_called_once()
        self.assertEqual(
            "[Warmup Timing] state=ready elapsed_seconds=%.3f",
            self.info_mock.call_args.args[0],
        )
        self.assertAlmostEqual(
            ready["elapsed_seconds"],
            self.info_mock.call_args.args[1],
            delta=0.05,
        )

        self.executor = ControlledExecutor()
        tts_routes._WARMUP_EXECUTOR = self.executor
        tts_routes._WARMUP_STATE = {
            "state": "cold",
            "started_at": None,
            "elapsed_seconds": None,
            "error": None,
        }
        self.service.fail = True
        self.client.post("/api/warmup")
        self.executor.run()
        failed = self.client.get("/api/warmup/status").get_json()
        self.assertEqual("failed", failed["state"])
        self.assertIn("simulated warmup failure", failed["error"])
        self.warning_mock.assert_called_once()
        self.assertEqual(
            "[Warmup Timing] state=failed elapsed_seconds=%.3f error=%s",
            self.warning_mock.call_args.args[0],
        )
        self.assertAlmostEqual(
            failed["elapsed_seconds"],
            self.warning_mock.call_args.args[1],
            delta=0.05,
        )
        self.assertEqual(
            "simulated warmup failure: \\u9884\\u70ed\\u5931\\u8d25",
            self.warning_mock.call_args.args[2],
        )
        self.assertTrue(self.warning_mock.call_args.args[2].isascii())

    def test_warmup_exception_always_clears_active_flag(self):
        self.service.fail = True
        self.service.mark_warmup_started()
        tts_routes._WARMUP_STATE.update(
            state="warming",
            started_at=0.0,
            elapsed_seconds=0.0,
            error=None,
        )

        tts_routes._warmup_worker()

        self.assertFalse(self.service.active)
        self.assertEqual(1, self.service.mark_finished_calls)
        self.assertEqual("failed", tts_routes._WARMUP_STATE["state"])

    def test_failed_synchronous_warmup_returns_failure_instead_of_raising(self):
        self.service.fail = True
        tts_routes._WARMUP_EXECUTOR = ImmediateExecutor()

        status = tts_routes.run_warmup_synchronously()

        self.assertEqual("failed", status["state"])
        self.assertIn("simulated warmup failure", status["error"])
        self.assertFalse(self.service.active)

    def test_synchronous_warmup_timeout_returns_while_worker_stays_active(self):
        sync_source = inspect.getsource(tts_routes.run_warmup_synchronously)
        self.assertIn("WARMUP_STARTUP_TIMEOUT_SECONDS", sync_source)
        self.assertNotIn("BENCHMARK_TIMEOUT_SECONDS", sync_source)

        with patch.object(tts_routes, "WARMUP_STARTUP_TIMEOUT_SECONDS", 0):
            status = tts_routes.run_warmup_synchronously()

        self.assertEqual("warming", status["state"])
        self.assertTrue(self.service.active)
        self.assertEqual(1, self.executor.submit_count)

        self.executor.run()
        self.assertFalse(self.service.active)
        self.assertEqual("ready", tts_routes._WARMUP_STATE["state"])


if __name__ == "__main__":
    unittest.main()
