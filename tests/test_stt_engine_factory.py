import unittest
from pathlib import Path

from engines.sherpa_parakeet import SherpaParakeetEngine
from engines.sherpa_sensevoice import SherpaSenseVoiceEngine
from stt_engine_factory import create_stt_engine


class SttEngineFactoryTests(unittest.TestCase):
    def test_arch_registry_returns_concrete_sensevoice_type(self) -> None:
        model_dir = Path("models/sensevoice-small-int8")

        engine = create_stt_engine(
            {"id": "custom-id", "name": "Custom ASR", "arch": "sensevoice"},
            model_dir,
        )

        self.assertIsInstance(engine, SherpaSenseVoiceEngine)
        self.assertEqual(model_dir, engine.model_dir)

    def test_name_fallback_preserves_parakeet_compatibility(self) -> None:
        model_dir = Path("models/parakeet-tdt-0.6b-v2-int8")

        engine = create_stt_engine(
            {"id": "legacy-asr", "name": "NVIDIA Parakeet TDT"},
            model_dir,
        )

        self.assertIsInstance(engine, SherpaParakeetEngine)
        self.assertEqual(model_dir, engine.model_dir)

    def test_unknown_engine_raises_original_error(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "Unsupported STT model engine for mystery-asr-int8: Mystery ASR",
        ):
            create_stt_engine(
                {"id": "mystery-asr-int8", "name": "Mystery ASR"},
                Path("models/mystery-asr-int8"),
            )


if __name__ == "__main__":
    unittest.main()
