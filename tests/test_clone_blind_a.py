from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf


APP_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = APP_ROOT / "tests" / "run_clone_blind_a.py"
SPEC = importlib.util.spec_from_file_location("run_clone_blind_a", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
blind = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(blind)


class CloneBlindATests(unittest.TestCase):
    def test_private_roots_are_outside_static(self) -> None:
        static_root = APP_ROOT / "static"

        self.assertFalse(blind._is_relative_to(blind.LISTEN_ROOT, static_root))
        self.assertFalse(blind._is_relative_to(blind.SEALED_ROOT, static_root))
        blind._assert_private_roots()
        self.assertEqual(2048, blind.STREAM_N_CTX)

    def test_parses_official_speaker_and_content_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            speaker_path = root / "spk-info.txt"
            content_path = root / "content.txt"
            speaker_path.write_text(
                "# voice-file name; age group; gender; accent\n"
                "SSB0005\tB\tfemale\tnorth\n"
                "SSB0394 B male north\n",
                encoding="utf-8",
            )
            content_path.write_text(
                "SSB00050001.wav\t你 ni3 好 hao3\n", encoding="utf-8"
            )

            speakers = blind._parse_speaker_info(speaker_path)
            content = blind._parse_content(content_path)

        self.assertEqual("female", speakers["SSB0005"]["gender"])
        self.assertEqual("B", speakers["SSB0394"]["age_group"])
        self.assertEqual("你好", content["ssb00050001.wav"]["text"])
        self.assertEqual("SSB00050001", content["ssb00050001"]["utterance_id"])

    def test_requires_gender_matched_age_and_accent_marginals(self) -> None:
        records = []
        for gender in ("male", "female"):
            records.extend(
                [
                    {
                        "speaker_id": f"{gender}-1",
                        "gender": gender,
                        "age_group": "B",
                        "accent": "north",
                    },
                    {
                        "speaker_id": f"{gender}-2",
                        "gender": gender,
                        "age_group": "B",
                        "accent": "south",
                    },
                    {
                        "speaker_id": f"{gender}-3",
                        "gender": gender,
                        "age_group": "C",
                        "accent": "north",
                    },
                    {
                        "speaker_id": f"{gender}-4",
                        "gender": gender,
                        "age_group": "C",
                        "accent": "south",
                    },
                ]
            )

        result = blind._validate_speaker_balance(records)
        self.assertTrue(result["marginals_matched_across_gender"])

        records[-1]["accent"] = "others"
        with self.assertRaisesRegex(RuntimeError, "accents are not matched"):
            blind._validate_speaker_balance(records)

    def test_selects_disjoint_two_or_three_clip_groups_in_duration_window(self) -> None:
        clips = [
            {"utterance_id": "u1", "duration_seconds": 5.1},
            {"utterance_id": "u2", "duration_seconds": 4.7},
            {"utterance_id": "u3", "duration_seconds": 4.4},
            {"utterance_id": "u4", "duration_seconds": 4.0},
            {"utterance_id": "u5", "duration_seconds": 3.9},
            {"utterance_id": "u6", "duration_seconds": 3.8},
        ]

        reference = blind._select_clip_group(clips)
        reference_ids = {item["utterance_id"] for item in reference}
        held_out = blind._select_clip_group(clips, excluded_ids=reference_ids)
        held_out_ids = {item["utterance_id"] for item in held_out}

        self.assertEqual(set(), reference_ids & held_out_ids)
        for group in (reference, held_out):
            duration = sum(item["duration_seconds"] for item in group)
            duration += blind.REFERENCE_GAP_SECONDS * (len(group) - 1)
            self.assertGreaterEqual(duration, blind.REFERENCE_MIN_SECONDS)
            self.assertLessEqual(duration, blind.REFERENCE_MAX_SECONDS)

    def test_selection_can_pair_a_long_clip_with_one_below_the_old_top_24(self) -> None:
        clips = [
            {"utterance_id": f"long-{index:02d}", "duration_seconds": 9.0}
            for index in range(30)
        ]
        clips.append({"utterance_id": "short", "duration_seconds": 0.9})

        selected = blind._select_clip_group(clips)

        self.assertEqual(2, len(selected))
        self.assertIn("short", {item["utterance_id"] for item in selected})
        duration = sum(item["duration_seconds"] for item in selected)
        duration += blind.REFERENCE_GAP_SECONDS
        self.assertAlmostEqual(10.1, duration)

    def test_prepares_hashed_24khz_mono_pcm16_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dataset_root = Path(temporary) / "data_aishell3"
            source_dir = dataset_root / "train" / "wav" / "SSB0005"
            source_dir.mkdir(parents=True)
            clips = []
            for index, duration in enumerate((4.4, 4.5), start=1):
                frames = round(44_100 * duration)
                phase = np.arange(frames, dtype=np.float32) / 44_100
                audio = 0.15 * np.sin(2 * np.pi * (180 + index * 20) * phase)
                path = source_dir / f"SSB0005{index:04d}.wav"
                sf.write(path, audio, 44_100, subtype="PCM_16")
                info = blind._audio_info(path)
                clips.append(
                    {
                        "utterance_id": path.stem,
                        "text": f"测试{index}",
                        "path": path,
                        **info,
                    }
                )
            output = Path(temporary) / "prepared.wav"

            record = blind._prepare_clip_group(dataset_root, clips, output)

            self.assertEqual(64, len(record["prepared_wav"]["sha256"]))
            self.assertEqual(24_000, record["prepared_wav"]["audio_format"]["sample_rate"])
            self.assertEqual(1, record["prepared_wav"]["audio_format"]["channels"])
            self.assertEqual("PCM_16", record["prepared_wav"]["audio_format"]["subtype"])
            self.assertGreaterEqual(
                record["prepared_wav"]["duration_seconds"],
                blind.REFERENCE_MIN_SECONDS,
            )
            self.assertLessEqual(
                record["prepared_wav"]["duration_seconds"],
                blind.REFERENCE_MAX_SECONDS,
            )

    def test_mapping_has_eight_primary_trials_plus_one_hidden_catch(self) -> None:
        speakers = [
            {"speaker_slot": f"speaker_{index:02d}", "speaker_id": f"SSB{index:04d}"}
            for index in range(1, 9)
        ]
        manifest = {
            "run_id": "test_run",
            "preregistration_sha256": "a" * 64,
            "speakers": speakers,
            "catch_trial": {"speaker_id": speakers[0]["speaker_id"]},
        }

        mapping = blind._new_mapping(manifest)
        kinds = [item["kind"] for item in mapping["trials"].values()]

        self.assertEqual(8, kinds.count("primary"))
        self.assertEqual(1, kinds.count("catch"))
        self.assertEqual(9, len(mapping["presentation_order"]))
        catch = next(item for item in mapping["trials"].values() if item["kind"] == "catch")
        self.assertIn("real_recording", catch["label_to_source"].values())
        self.assertIn(catch["synthetic_arm"], {"base", "custom_voice"})

    def test_preregistered_decision_threshold_and_catch_gate(self) -> None:
        self.assertEqual(
            "retain_base",
            blind._decision_for_counts(
                catch_passed=True, base_wins=6, custom_wins=2
            )[0],
        )
        self.assertEqual(
            "delete_base",
            blind._decision_for_counts(
                catch_passed=True, base_wins=5, custom_wins=3
            )[0],
        )
        self.assertEqual(
            "invalid_repeat",
            blind._decision_for_counts(
                catch_passed=False, base_wins=8, custom_wins=0
            )[0],
        )


if __name__ == "__main__":
    unittest.main()
