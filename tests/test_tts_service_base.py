import os
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import local_tts_engine as dispatcher
import local_tts_engine_gguf as gguf
import local_tts_engine_pytorch as pytorch
from local_tts_service_base import LocalTTSBusyError, LocalTTSError, LocalTTSServiceBase


class TtsServiceBaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pytorch_service = pytorch.LocalTTSService()
        self.gguf_service = gguf.LocalTTSService()

    def test_resolve_speaker_supports_default_id_and_alias(self) -> None:
        for service in (self.pytorch_service, self.gguf_service):
            with self.subTest(service=type(service).__module__):
                default_speaker = service.resolve_speaker(None)
                self.assertEqual("uncle_fu", default_speaker["id"])
                self.assertIs(default_speaker, service.resolve_speaker("Uncle Fu"))

    def test_resolve_speaker_rejects_unknown_id(self) -> None:
        for service, error_type in (
            (self.pytorch_service, pytorch.LocalTTSError),
            (self.gguf_service, gguf.LocalTTSError),
        ):
            with self.subTest(service=type(service).__module__):
                with self.assertRaises(error_type):
                    service.resolve_speaker("missing-speaker")

    def test_resolve_language_preserves_backend_specific_casing(self) -> None:
        speaker = self.pytorch_service.resolve_speaker("uncle_fu")

        self.assertEqual("Chinese", self.pytorch_service.resolve_language(speaker))
        self.assertEqual("chinese", self.gguf_service.resolve_language(speaker))

    def test_voice_catalog_is_shared_and_complete(self) -> None:
        pytorch_catalog = self.pytorch_service.get_voice_catalog()
        gguf_catalog = self.gguf_service.get_voice_catalog()

        self.assertEqual(pytorch_catalog, gguf_catalog)
        self.assertEqual("uncle_fu", pytorch_catalog["_meta"]["default_voice"])
        self.assertEqual(
            ["_meta", "all", "zh", "en", "ja", "ko"],
            list(pytorch_catalog),
        )

    def test_dispatcher_reexports_selected_backend_exception_types(self) -> None:
        selected_backend = gguf if os.environ.get("USE_GGUF_BACKEND") == "1" else pytorch

        self.assertIs(dispatcher.LocalTTSError, selected_backend.LocalTTSError)
        self.assertIs(dispatcher.LocalTTSBusyError, selected_backend.LocalTTSBusyError)

    def test_backends_share_base_and_exception_identity(self) -> None:
        self.assertTrue(issubclass(pytorch.LocalTTSService, LocalTTSServiceBase))
        self.assertTrue(issubclass(gguf.LocalTTSService, LocalTTSServiceBase))
        self.assertIs(pytorch.LocalTTSError, LocalTTSError)
        self.assertIs(gguf.LocalTTSError, LocalTTSError)
        self.assertIs(pytorch.LocalTTSBusyError, LocalTTSBusyError)
        self.assertIs(gguf.LocalTTSBusyError, LocalTTSBusyError)

    def test_synthesis_waits_for_active_warmup_then_succeeds(self) -> None:
        for service in (self.pytorch_service, self.gguf_service):
            with self.subTest(service=type(service).__module__):
                service.mark_warmup_started()
                service._busy_lock.acquire()
                release_timer = threading.Timer(0.05, service._busy_lock.release)
                release_timer.start()
                try:
                    with patch.object(
                        service,
                        "_generate_mp3_no_lock",
                        return_value="warmup-wait.mp3",
                    ):
                        result = service.synthesize_text("测试", None)
                finally:
                    release_timer.join()
                    if service._busy_lock.locked():
                        service._busy_lock.release()
                    service.mark_warmup_finished()

                self.assertEqual("warmup-wait.mp3", result)

    def test_normal_synthesis_conflict_stays_immediate(self) -> None:
        for service in (self.pytorch_service, self.gguf_service):
            with self.subTest(service=type(service).__module__):
                service._busy_lock.acquire()
                started = time.perf_counter()
                try:
                    with self.assertRaises(LocalTTSBusyError):
                        service.synthesize_text("测试", None)
                finally:
                    service._busy_lock.release()

                self.assertLess(time.perf_counter() - started, 1.0)

    def _invoke_stream_entry(self, service, entry_point):
        with ExitStack() as stack:
            if service is self.pytorch_service:
                if entry_point == "sentences":
                    stack.enter_context(
                        patch.object(
                            service,
                            "_iter_sentence_events",
                            return_value=iter(()),
                        )
                    )
                    return service.synthesize_sentences_stream(["测试。"], None)

                stack.enter_context(patch.object(pytorch.threading, "Thread"))
                stack.enter_context(
                    patch.object(
                        service,
                        "_iter_long_from_queue",
                        return_value=iter(()),
                    )
                )
                return service.synthesize_long_stream("测试长文本。", None)

            stack.enter_context(patch.object(gguf.threading, "Thread"))
            stack.enter_context(
                patch.object(service, "_iter_from_queue", return_value=iter(()))
            )
            if entry_point == "sentences":
                stack.enter_context(
                    patch.object(
                        service,
                        "_normalize_and_split_chunks",
                        return_value=["测试。"],
                    )
                )
                return service.synthesize_sentences_stream(["测试。"], None)

            stack.enter_context(
                patch.object(service, "_long_groups", return_value=["测试长文本。"])
            )
            return service.synthesize_long_stream("测试长文本。", None)

    def test_streaming_entries_wait_for_active_warmup_then_succeed(self) -> None:
        for service in (self.pytorch_service, self.gguf_service):
            for entry_point in ("sentences", "long"):
                with self.subTest(
                    service=type(service).__module__,
                    entry_point=entry_point,
                ):
                    service.mark_warmup_started()
                    service._busy_lock.acquire()
                    release_timer = threading.Timer(0.05, service._busy_lock.release)
                    release_timer.start()
                    started = time.perf_counter()
                    try:
                        result = self._invoke_stream_entry(service, entry_point)
                    finally:
                        elapsed = time.perf_counter() - started
                        release_timer.join()
                        if service._busy_lock.locked():
                            service._busy_lock.release()
                        service.mark_warmup_finished()

                    self.assertIsNotNone(result)
                    self.assertGreaterEqual(elapsed, 0.03)

    def test_streaming_entries_keep_normal_conflicts_immediate(self) -> None:
        for service in (self.pytorch_service, self.gguf_service):
            for entry_point in ("sentences", "long"):
                with self.subTest(
                    service=type(service).__module__,
                    entry_point=entry_point,
                ):
                    service._busy_lock.acquire()
                    started = time.perf_counter()
                    try:
                        with self.assertRaises(LocalTTSBusyError):
                            self._invoke_stream_entry(service, entry_point)
                    finally:
                        service._busy_lock.release()

                    self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
