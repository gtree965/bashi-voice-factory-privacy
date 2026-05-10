LANGUAGE_LABELS = {
    "zh": {"en": "Chinese", "zh": "中文"},
    "en": {"en": "English", "zh": "英文"},
    "ja": {"en": "Japanese", "zh": "日语"},
    "ko": {"en": "Korean", "zh": "韩语"},
}

VOICE_CATEGORIES = [
    ("all", "All speakers", "全部音色"),
    ("zh", "Chinese", "中文"),
    ("en", "English", "英文"),
    ("ja", "Japanese", "日语"),
    ("ko", "Korean", "韩语"),
]

FALLBACK_GENDER = {
    "uncle_fu": "Male",
    "dylan": "Male",
    "eric": "Male",
    "ryan": "Male",
    "aiden": "Male",
    "vivian": "Female",
    "serena": "Female",
    "ono_anna": "Female",
    "sohee": "Female",
}

GENDER_LABELS = {
    "Male": {"en": "Male", "zh": "男性"},
    "Female": {"en": "Female", "zh": "女性"},
    "Unknown": {"en": "Unknown", "zh": "未知"},
}


def build_voice_catalog(speaker_registry: dict) -> dict:
    speakers = list(speaker_registry["by_id"].values())
    default_speaker = speaker_registry["default_speaker"]
    catalog = {
        "_meta": {
            "default_voice": default_speaker,
            "model_family": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
        }
    }

    for category, label_en, label_zh in VOICE_CATEGORIES:
        visible_speakers = _filter_speakers(speakers, category)
        voices = [_format_voice(speaker, category) for speaker in sorted(
            visible_speakers,
            key=lambda item: _sort_key(item, category, default_speaker),
        )]
        catalog[category] = {
            "category": label_en,
            "category_en": label_en,
            "category_zh": label_zh,
            "voices": voices,
        }

    return catalog


def _filter_speakers(speakers: list[dict], category: str) -> list[dict]:
    if category == "all":
        return speakers
    return [
        speaker
        for speaker in speakers
        if speaker.get("native_language") == category
        or category in speaker.get("recommended_for", [])
    ]


def _sort_key(speaker: dict, category: str, default_speaker: str):
    language_order = {"zh": 0, "en": 1, "ja": 2, "ko": 3}
    if category == "all":
        return (
            0 if speaker["id"] == default_speaker else 1,
            language_order.get(speaker.get("native_language"), 99),
            speaker["display_name"].lower(),
        )

    recommended = category in speaker.get("recommended_for", [])
    native = speaker.get("native_language") == category
    return (
        0 if speaker["id"] == default_speaker else 1,
        0 if recommended else 1,
        0 if native else 1,
        speaker["display_name"].lower(),
    )


def _format_voice(speaker: dict, category: str) -> dict:
    native_language = speaker.get("native_language", "")
    language_label = LANGUAGE_LABELS.get(
        native_language,
        {"en": native_language.upper(), "zh": native_language.upper()},
    )
    gender = FALLBACK_GENDER.get(speaker["id"], "Unknown")
    gender_label = GENDER_LABELS.get(gender, GENDER_LABELS["Unknown"])
    badges = []
    if category != "all" and category in speaker.get("recommended_for", []):
        badges.append({"en": "Recommended", "zh": "推荐"})
    if native_language:
        badges.append({"en": f"Native {language_label['en']}", "zh": f"原生{language_label['zh']}"})

    return {
        "id": speaker["id"],
        "name": speaker["display_name"],
        "gender": gender,
        "gender_en": gender_label["en"],
        "gender_zh": gender_label["zh"],
        "native_language": native_language,
        "language_label_en": language_label["en"],
        "language_label_zh": language_label["zh"],
        "recommended_for": speaker.get("recommended_for", []),
        "style": speaker.get("notes", ""),
        "style_en": speaker.get("notes", ""),
        "style_zh": speaker.get("notes_zh", speaker.get("notes", "")),
        "badges": badges,
    }
