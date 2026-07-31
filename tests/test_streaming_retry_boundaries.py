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
