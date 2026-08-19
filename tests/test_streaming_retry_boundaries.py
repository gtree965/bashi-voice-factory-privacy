import re
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


class StreamingRetryBoundaryTests(unittest.TestCase):
    def test_restart_wait_is_frontend_only_and_routes_keep_immediate_409(self) -> None:
        routes = (APP_ROOT / "tts_routes.py").read_text(encoding="utf-8")
        frontend = (APP_ROOT / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )

        for forbidden in ("X-Bashi-Retry-After-Stop", "_call_with_restart_wait"):
            with self.subTest(forbidden=forbidden, source="routes"):
                self.assertNotIn(forbidden, routes)
            with self.subTest(forbidden=forbidden, source="frontend"):
                self.assertNotIn(forbidden, frontend)

        for route_name in ("synthesize", "synthesize_long", "synthesize_sentences"):
            start = routes.index(f"def {route_name}(")
            end = routes.find("\n@tts_bp.route", start)
            section = routes[start : end if end >= 0 else None]
            with self.subTest(route=route_name):
                self.assertRegex(
                    section,
                    re.compile(
                        r"except LocalTTSBusyError as exc:\n"
                        r"\s+return _json_error\(str\(exc\), 409\)"
                    ),
                )

        self.assertIn("import time", routes)
        self.assertIn("RESTART_RETRY_BUDGET_MS = 60000", frontend)
        self.assertIn("waitForRetryDelay(backoffMs, signal)", frontend)
        with self.subTest(boundary="restart_retry_delay_cap"):
            self.assertIn("RESTART_RETRY_MAX_DELAY_MS = 750", frontend)

        with self.subTest(boundary="warmup_has_independent_real_synthesis_text"):
            self.assertIn(
                'WARMUP_TEXT = "今天下午三点，我们将在会议室讨论项目进展和预算表。"',
                routes,
            )
            self.assertNotIn("WARMUP_TEXT = BENCHMARK_TEXT", routes)
            self.assertNotIn("WARMUP_TEXT = BENCHMARK_WARMUP_TEXT", routes)
            self.assertIn("benchmark wording and UI cold-start coverage", routes)

        with self.subTest(boundary="warmup_polling_preserves_server_state_on_transient_failure"):
            poll_start = frontend.index("async function pollWarmupStatus()")
            poll_end = frontend.index("\n}\n\nfunction startWarmup", poll_start)
            poll_section = frontend[poll_start:poll_end]
            catch_section = poll_section[poll_section.index("} catch (_) {") :]
            self.assertIn(
                "WARMUP_STATUS_RETRY_DELAYS_MS = [1500, 5000, 15000]",
                frontend,
            )
            self.assertIn("scheduleWarmupStatusPoll", catch_section)
            self.assertNotIn("applyWarmupStatus({ state: 'failed'", catch_section)

        with self.subTest(boundary="warmup_start_retries_without_false_failed_state"):
            start_start = frontend.index("function startWarmup(")
            start_end = frontend.index("\n}\n\nfunction renderBenchmarkReferencePanel", start_start)
            start_section = frontend[start_start:start_end]
            self.assertIn("WARMUP_STATUS_RETRY_DELAYS_MS", start_section)
            self.assertIn("startWarmup(retryCount + 1)", start_section)
            self.assertNotIn("applyWarmupStatus({ state: 'failed'", start_section)

        with self.subTest(boundary="warmup_polling_slows_after_chip_ceiling"):
            poll_start = frontend.index("async function pollWarmupStatus()")
            poll_end = frontend.index("\n}\n\nfunction startWarmup", poll_start)
            poll_section = frontend[poll_start:poll_end]
            self.assertIn("shouldSuppressBackendChipForWarmup()", poll_section)
            self.assertIn("WARMUP_STATUS_POLL_DELAY_MS", poll_section)
            self.assertIn("WARMUP_STATUS_MAX_RETRY_DELAY_MS", poll_section)

        with self.subTest(boundary="warmup_chip_cap_uses_server_wait_but_loading_copy_does_not"):
            render_start = frontend.index("function renderSystemInfo()")
            render_end = frontend.index("\n}\n\nfunction getObservedWarmupElapsedSeconds", render_start)
            render_section = frontend[render_start:render_end]
            suppress_start = frontend.index("function shouldSuppressBackendChipForWarmup()")
            suppress_end = frontend.index("\n}\n\nfunction applyWarmupStatus", suppress_start)
            suppress_section = frontend[suppress_start:suppress_end]
            self.assertIn("shouldSuppressBackendChipForWarmup()", render_section)
            self.assertIn("waitTimeoutSeconds", suppress_section)
            self.assertIn("WARMUP_STATUS_MAX_RETRY_DELAY_MS", suppress_section)
            self.assertIn('"wait_timeout_seconds": WARMUP_WAIT_TIMEOUT', routes)
            self.assertGreaterEqual(
                frontend.count("state.warmup.state === 'warming'"),
                2,
            )

        with self.subTest(boundary="warmup_starts_before_other_ui_requests"):
            init_start = frontend.index("async function init()")
            init_end = frontend.index("\n}", init_start)
            init_section = frontend[init_start:init_end]
            self.assertLess(init_section.index("startWarmup();"), init_section.index("await loadVoices();"))

        with self.subTest(boundary="warmup_loading_copy_is_bilingual"):
            self.assertIn("Warming up the engine; synthesis will start shortly…", frontend)
            self.assertIn("正在预热引擎，稍后自动开始…", frontend)
            self.assertIn("Warming up engine...", frontend)
            self.assertIn("正在预热引擎…", frontend)

        with self.subTest(boundary="complete_audio_takes_over_preview"):
            listener_start = frontend.index("elements.audioPlayer?.addEventListener('play'")
            listener_end = frontend.index("\n    });", listener_start)
            listener_section = frontend[listener_start:listener_end]
            self.assertIn("haltLongPreviewAudio()", listener_section)

        with self.subTest(boundary="preview_reset_preserves_cross_run_timing"):
            reset_start = frontend.index("function resetLongPreviewState()")
            reset_end = frontend.index("\n}\n\nfunction haltLongPreviewAudio", reset_start)
            reset_section = frontend[reset_start:reset_end]
            self.assertNotIn("lastGroupSeconds", reset_section)

        long_section = frontend[
            frontend.index("async function generateLongAudio") :
            frontend.index("async function generateSentences")
        ]
        self.assertIn("if (!response.ok)", long_section)

        with self.subTest(boundary="stale_long_done_cannot_take_over_player"):
            done_start = long_section.index("else if (data.status === 'done')")
            done_end = long_section.index(
                "else if (data.status === 'error')", done_start
            )
            done_section = long_section[done_start:done_end]
            self.assertIn("if (runToken !== state.runToken)", done_section)
            self.assertIn("elements.audioPlayer.src = data.audio_url_mp3", done_section)

        with self.subTest(boundary="generating_count_keeps_current_group_semantics"):
            generating_start = long_section.index(
                "if (data.status === 'generating')"
            )
            generating_end = long_section.index(
                "else if (data.status === 'chunk_done')", generating_start
            )
            generating_section = long_section[generating_start:generating_end]
            self.assertIn(
                "countEl.textContent = `${data.chunk} / ${data.total}`",
                generating_section,
            )
            self.assertIn("if (runToken !== state.runToken)", generating_section)

        with self.subTest(boundary="stale_preview_chunk_cannot_restart_playback"):
            preview_start = frontend.index("function handleLongPreviewChunk")
            preview_end = frontend.index("\n}\n\n// Generate Long Audio", preview_start)
            preview_section = frontend[preview_start:preview_end]
            self.assertIn("if (runToken !== state.runToken) return", preview_section)
            self.assertIn("handleLongPreviewChunk(data, runToken)", long_section)

        with self.subTest(boundary="restart_status_is_run_scoped"):
            self.assertIn("runToken: 0", frontend)
            self.assertIn("const runToken = ++state.runToken", frontend)
            for helper in ("showRestartRetryStatus", "clearRestartRetryStatus"):
                helper_start = frontend.index(f"function {helper}")
                helper_end = frontend.index("\n}\n", helper_start)
                helper_section = frontend[helper_start:helper_end]
                self.assertIn("runToken !== state.runToken", helper_section)

        with self.subTest(boundary="all_409_responses_use_honest_retry_status"):
            retry_start = frontend.index("async function postSynthesisWithRetry")
            retry_end = frontend.index("// Generate Single Audio", retry_start)
            retry_section = frontend[retry_start:retry_end]
            self.assertIn("if (response.status !== 409)", retry_section)
            self.assertNotIn(
                "response.status !== 409 || !retryAfterStop", retry_section
            )
            self.assertIn(
                "Waiting for the current synthesis to finish...", frontend
            )
            self.assertIn("上一次合成仍在进行，正在等待…", frontend)
            self.assertIn("Stopping previous synthesis...", frontend)
            self.assertIn("正在停止上一次合成…", frontend)

        with self.subTest(boundary="long_progress_playout_mode"):
            self.assertIn("function setLongProgressPlayoutMode(mode)", frontend)
            self.assertGreaterEqual(
                long_section.count("setLongProgressPlayoutMode("),
                3,
            )
            for mode in ("null", "'stopped'", "'completed'"):
                self.assertIn(f"setLongProgressPlayoutMode({mode})", long_section)

        template = (APP_ROOT / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        with self.subTest(boundary="long_progress_playout_hooks"):
            for element_id in (
                "long-progress-headline",
                "long-progress-metrics",
                "long-progress-hint",
            ):
                self.assertIn(f'id="{element_id}"', template)


if __name__ == "__main__":
    unittest.main()
