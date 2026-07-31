import unittest

from local_voice_catalog import build_voice_catalog


class VoiceCatalogTests(unittest.TestCase):
    def test_catalog_exposes_only_local_speaker_categories(self) -> None:
        catalog = build_voice_catalog(
            {
                "default_speaker": "uncle_fu",
                "by_id": {
                    "uncle_fu": {
                        "id": "uncle_fu",
                        "display_name": "福伯 Uncle_Fu",
                        "native_language": "zh",
                        "recommended_for": ["zh"],
                        "notes": "Seasoned male voice.",
                        "notes_zh": "沉稳男声。",
                    },
                    "ryan": {
                        "id": "ryan",
                        "display_name": "甜茶 Ryan",
                        "native_language": "en",
                        "recommended_for": ["en"],
                        "notes": "Dynamic male voice.",
                    },
                    "ono_anna": {
                        "id": "ono_anna",
                        "display_name": "小野杏 Ono_Anna",
                        "native_language": "ja",
                        "recommended_for": ["ja"],
                        "notes": "Playful Japanese female voice.",
                    },
                    "sohee": {
                        "id": "sohee",
                        "display_name": "素熙 Sohee",
                        "native_language": "ko",
                        "recommended_for": ["ko"],
                        "notes": "Warm Korean female voice.",
                    },
                },
            }
        )

        self.assertEqual(["_meta", "all", "zh", "en", "ja", "ko"], list(catalog.keys()))
        self.assertEqual("uncle_fu", catalog["_meta"]["default_voice"])
        self.assertEqual(["uncle_fu"], [voice["id"] for voice in catalog["zh"]["voices"]])
        uncle_fu = catalog["zh"]["voices"][0]
        self.assertEqual("Seasoned male voice.", uncle_fu["style_en"])
        self.assertEqual("沉稳男声。", uncle_fu["style_zh"])
        self.assertEqual("福伯 Uncle_Fu", uncle_fu["name"])
        self.assertEqual("Male", uncle_fu["gender"])
        self.assertEqual("Male", uncle_fu["gender_en"])
        self.assertEqual("男性", uncle_fu["gender_zh"])
        self.assertEqual(["ryan"], [voice["id"] for voice in catalog["en"]["voices"]])
        self.assertEqual(["ono_anna"], [voice["id"] for voice in catalog["ja"]["voices"]])
        self.assertEqual(["sohee"], [voice["id"] for voice in catalog["ko"]["voices"]])
        self.assertEqual("女性", catalog["ko"]["voices"][0]["gender_zh"])

    def test_all_category_keeps_default_speaker_first(self) -> None:
        catalog = build_voice_catalog(
            {
                "default_speaker": "uncle_fu",
                "by_id": {
                    "ryan": {
                        "id": "ryan",
                        "display_name": "甜茶 Ryan",
                        "native_language": "en",
                        "recommended_for": ["en"],
                        "notes": "",
                    },
                    "uncle_fu": {
                        "id": "uncle_fu",
                        "display_name": "福伯 Uncle_Fu",
                        "native_language": "zh",
                        "recommended_for": ["zh"],
                        "notes": "",
                    },
                },
            }
        )

        self.assertEqual("uncle_fu", catalog["all"]["voices"][0]["id"])


if __name__ == "__main__":
    unittest.main()
