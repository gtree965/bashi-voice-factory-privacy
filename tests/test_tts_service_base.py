import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
