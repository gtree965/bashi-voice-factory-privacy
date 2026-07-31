import unittest

import numpy as np

from audio_encoding import DEFAULT_TARGET_PEAK_DBFS, peak_normalize_audio


class PeakNormalizeAudioTests(unittest.TestCase):
    def test_scales_peak_to_default_minus_one_dbfs(self):
        audio = np.array([0.0, 0.25, -0.5, 0.125], dtype=np.float32)

        normalized = peak_normalize_audio(audio)

        target_peak = 10 ** (DEFAULT_TARGET_PEAK_DBFS / 20.0)
        self.assertAlmostEqual(target_peak, float(np.max(np.abs(normalized))), places=6)
        self.assertEqual(np.float32, normalized.dtype)

    def test_reduces_overfull_audio_without_exceeding_target(self):
        audio = np.array([0.0, 2.0, -1.0], dtype=np.float32)

        normalized = peak_normalize_audio(audio)

        target_peak = 10 ** (DEFAULT_TARGET_PEAK_DBFS / 20.0)
        self.assertLessEqual(float(np.max(normalized)), target_peak)
        self.assertGreaterEqual(float(np.min(normalized)), -target_peak)
        self.assertAlmostEqual(target_peak, float(np.max(np.abs(normalized))), places=6)

    def test_preserves_silence(self):
        audio = np.zeros(8, dtype=np.float32)

        normalized = peak_normalize_audio(audio)

        np.testing.assert_array_equal(audio, normalized)

    def test_preserves_shape_for_multichannel_audio(self):
        audio = np.array([[0.1, -0.2], [0.3, -0.4]], dtype=np.float32)

        normalized = peak_normalize_audio(audio)

        self.assertEqual(audio.shape, normalized.shape)
        target_peak = 10 ** (DEFAULT_TARGET_PEAK_DBFS / 20.0)
        self.assertAlmostEqual(target_peak, float(np.max(np.abs(normalized))), places=6)


if __name__ == "__main__":
    unittest.main()
