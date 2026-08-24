"""Prepare, run, and score the sealed Base-vs-CustomVoice clone blind test.

This is an offline experiment runner, not product code. Real reference audio,
generated audio, arm mappings, and reports stay below ``.tmp/clone_blind_a``;
nothing is written below Flask's ``static/`` tree.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import itertools
import json
import math
import multiprocessing
import os
import re
import secrets
import shutil
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


APP_ROOT = Path(
    os.environ.get("BASHI_APP_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
REPO_ROOT = APP_ROOT.parent
LISTEN_ROOT = APP_ROOT / ".tmp" / "clone_blind_a" / "listen"
SEALED_ROOT = APP_ROOT / ".tmp" / "clone_blind_a" / "sealed"

DEFAULT_PROBE_ROOT = (
    REPO_ROOT / "vulkan_backend_spike" / "Qwen3-TTS-GGUF-0eb32e2-probe"
)
DEFAULT_BASE_MODEL_DIR = APP_ROOT / ".tmp" / "m0_exports" / "base"
DEFAULT_CUSTOM_MODEL_DIR = (
    APP_ROOT / ".tmp" / "m0_exports" / "custom_with_speaker_probe"
)

SCHEMA_VERSION = 2
SAMPLE_RATE = 24_000
REFERENCE_MIN_SECONDS = 8.0
REFERENCE_MAX_SECONDS = 12.0
REFERENCE_TARGET_SECONDS = 10.0
REFERENCE_GAP_SECONDS = 0.2
OUTPUT_GAP_SECONDS = 0.35
STREAM_N_CTX = 2048
OFFICIAL_ARCHIVE_NAME = "data_aishell3.tgz"
OFFICIAL_ARCHIVE_MD5 = "6833e9dcb47709d4e153e2f669e5ddc8"
OFFICIAL_SOURCE_URL = "https://www.openslr.org/93/"
DECISION_RULE = {
    "retain_base": "base_wins_greater_than_or_equal_to_6_of_8",
    "delete_base": "base_wins_less_than_or_equal_to_5_of_8",
    "catch_failure": "invalidate_and_repeat_before_any_package_decision",
}

TARGET_TEXTS = (
    "清晨的服务中心先核对设备状态，再按照当天的清单安排巡检任务。",
    "工作人员完成资料复核以后，把需要继续处理的事项逐项记录下来。",
    "傍晚的天气逐渐转凉，值班人员关闭侧门，并确认备用电源运行正常。",
)
CATCH_TARGET_TEXT = (
    "为了检查这次试听是否足够灵敏，请根据声音本身作出选择，不要参考文件顺序。"
)
GENERATION_CONFIG = {
    "streaming": False,
    "seed": 42,
    "sub_seed": 43,
    "temperature": 0.7,
    "sub_temperature": 0.7,
    "top_p": 0.85,
    "sub_top_p": 0.85,
    "top_k": 50,
    "sub_top_k": 50,
    "max_steps": 450,
}

MODEL_CORE_FILES = (
    "qwen3_tts_talker.q5_k.gguf",
    "qwen3_tts_predictor.q8_0.gguf",
    "qwen3_tts_decoder.fp16.onnx",
    "qwen3_tts_codec_encoder.fp16.onnx",
    "qwen3_tts_speaker_encoder.fp16.onnx",
    "tokenizer.json",
)
SINGLE_VARIABLE_FILES = (
    "qwen3_tts_decoder.fp16.onnx",
    "qwen3_tts_codec_encoder.fp16.onnx",
    "qwen3_tts_speaker_encoder.fp16.onnx",
    "tokenizer.json",
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_private_roots() -> None:
    static_root = (APP_ROOT / "static").resolve()
    for name, root in (("LISTEN_ROOT", LISTEN_ROOT), ("SEALED_ROOT", SEALED_ROOT)):
        resolved = root.resolve()
        if _is_relative_to(resolved, static_root):
            raise RuntimeError(f"{name} must not be inside static/: {resolved}")
        expected_parent = (APP_ROOT / ".tmp" / "clone_blind_a").resolve()
        if not _is_relative_to(resolved, expected_parent):
            raise RuntimeError(f"{name} escaped the private experiment root: {resolved}")


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    return run_id


def _new_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_hashes(path: Path, algorithms: Sequence[str]) -> dict[str, str]:
    digests = {name: hashlib.new(name) for name in algorithms}
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            for digest in digests.values():
                digest.update(block)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_hash_sidecar(path: Path) -> str:
    value = path.read_text(encoding="ascii").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(f"invalid SHA-256 sidecar: {path}")
    return value


def _write_hash_sidecar(path: Path, value: str) -> None:
    path.write_text(value.lower() + "\n", encoding="ascii")


def _audio_info(path: Path) -> dict[str, Any]:
    import soundfile as sf

    info = sf.info(str(path))
    return {
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "frames": int(info.frames),
        "duration_seconds": round(float(info.duration), 6),
        "subtype": str(info.subtype),
    }


def _audio_metrics(audio: np.ndarray) -> dict[str, Any]:
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim != 1 or values.size == 0:
        raise RuntimeError(f"expected non-empty mono audio, got shape={values.shape}")
    if not np.isfinite(values).all():
        raise RuntimeError("audio contains non-finite samples")
    peak = float(np.max(np.abs(values)))
    rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    if peak <= 0.0 or rms <= 1e-7:
        raise RuntimeError(f"audio is silent: peak={peak} rms={rms}")
    return {
        "samples": int(values.size),
        "duration_seconds": round(values.size / SAMPLE_RATE, 6),
        "peak": peak,
        "rms": rms,
    }


def _read_audio_24k(path: Path) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim == 2:
        values = values.mean(axis=1)
    if values.ndim != 1 or values.size == 0:
        raise RuntimeError(f"unsupported or empty audio: {path}")
    if sample_rate != SAMPLE_RATE:
        divisor = math.gcd(int(sample_rate), SAMPLE_RATE)
        values = resample_poly(
            values,
            SAMPLE_RATE // divisor,
            int(sample_rate) // divisor,
        ).astype(np.float32, copy=False)
    return values


def _write_pcm16_wav(path: Path, audio: np.ndarray) -> dict[str, Any]:
    import soundfile as sf

    values = np.asarray(audio, dtype=np.float32)
    metrics = _audio_metrics(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(values, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16")
    info = _audio_info(path)
    if (
        info["sample_rate"] != SAMPLE_RATE
        or info["channels"] != 1
        or info["subtype"] != "PCM_16"
    ):
        raise RuntimeError(f"prepared WAV contract failed for {path}: {info}")
    return {
        **metrics,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "audio_format": info,
    }


def _join_wavs(paths: Sequence[Path], gap_seconds: float) -> np.ndarray:
    parts: list[np.ndarray] = []
    gap = np.zeros(round(SAMPLE_RATE * gap_seconds), dtype=np.float32)
    for index, path in enumerate(paths):
        info = _audio_info(path)
        if info["sample_rate"] != SAMPLE_RATE or info["channels"] != 1:
            raise RuntimeError(f"input WAV is not 24 kHz mono: {path}: {info}")
        values = _read_audio_24k(path)
        if index:
            parts.append(gap)
        parts.append(values)
    if not parts:
        raise RuntimeError("cannot join an empty WAV list")
    return np.concatenate(parts).astype(np.float32, copy=False)


def _resolve_dataset_root(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    candidates = (resolved, resolved / "data_aishell3")
    for candidate in candidates:
        if (
            (candidate / "spk-info.txt").is_file()
            and (candidate / "train" / "content.txt").is_file()
            and (candidate / "train" / "wav").is_dir()
        ):
            return candidate.resolve()
    raise RuntimeError(
        "AISHELL-3 root must contain spk-info.txt, train/content.txt, and train/wav"
    )


def _parse_speaker_info(path: Path) -> dict[str, dict[str, str]]:
    speakers: dict[str, dict[str, str]] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise RuntimeError(f"bad spk-info row at {path}:{line_number}: {raw!r}")
        speaker_id, age_group, gender, accent = fields
        record = {
            "speaker_id": speaker_id,
            "age_group": age_group.upper(),
            "gender": gender.lower(),
            "accent": accent.lower(),
        }
        previous = speakers.get(speaker_id)
        if previous is not None and previous != record:
            raise RuntimeError(f"conflicting spk-info rows for {speaker_id}")
        speakers[speaker_id] = record
    if not speakers:
        raise RuntimeError(f"no speakers parsed from {path}")
    return speakers


def _parse_content(path: Path) -> dict[str, dict[str, str]]:
    content: dict[str, dict[str, str]] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t", 1)
        if len(fields) != 2:
            fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise RuntimeError(f"bad content row at {path}:{line_number}: {raw!r}")
        file_name, annotated = fields
        tokens = annotated.split()
        if len(tokens) < 2:
            raise RuntimeError(f"empty transcript at {path}:{line_number}")
        text = "".join(tokens[0::2])
        record = {"utterance_id": Path(file_name).stem, "text": text}
        content[Path(file_name).name.lower()] = record
        content[Path(file_name).stem.lower()] = record
    if not content:
        raise RuntimeError(f"no transcripts parsed from {path}")
    return content


def _validate_speaker_balance(records: Sequence[dict[str, str]]) -> dict[str, Any]:
    if len(records) != 8:
        raise RuntimeError(f"exactly 8 speakers are required, got {len(records)}")
    if len({item["speaker_id"] for item in records}) != 8:
        raise RuntimeError("speaker IDs must be unique")
    genders = Counter(item["gender"] for item in records)
    if genders != Counter({"male": 4, "female": 4}):
        raise RuntimeError(f"speaker selection must be 4 male / 4 female: {dict(genders)}")

    by_gender: dict[str, dict[str, Counter[str]]] = {}
    for gender in ("male", "female"):
        selected = [item for item in records if item["gender"] == gender]
        by_gender[gender] = {
            "age_group": Counter(item["age_group"] for item in selected),
            "accent": Counter(item["accent"] for item in selected),
        }
    if by_gender["male"]["age_group"] != by_gender["female"]["age_group"]:
        raise RuntimeError(
            "age groups are not matched across gender: "
            f"male={dict(by_gender['male']['age_group'])} "
            f"female={dict(by_gender['female']['age_group'])}"
        )
    if by_gender["male"]["accent"] != by_gender["female"]["accent"]:
        raise RuntimeError(
            "accents are not matched across gender: "
            f"male={dict(by_gender['male']['accent'])} "
            f"female={dict(by_gender['female']['accent'])}"
        )
    return {
        "gender_counts": dict(sorted(genders.items())),
        "male_age_groups": dict(sorted(by_gender["male"]["age_group"].items())),
        "female_age_groups": dict(sorted(by_gender["female"]["age_group"].items())),
        "male_accents": dict(sorted(by_gender["male"]["accent"].items())),
        "female_accents": dict(sorted(by_gender["female"]["accent"].items())),
        "marginals_matched_across_gender": True,
    }


def _speaker_clips(
    dataset_root: Path,
    speaker_id: str,
    content: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    speaker_dir = dataset_root / "train" / "wav" / speaker_id
    if not speaker_dir.is_dir():
        raise RuntimeError(f"missing train WAV directory for {speaker_id}: {speaker_dir}")
    clips: list[dict[str, Any]] = []
    for path in sorted(speaker_dir.glob("*.wav")):
        transcript = content.get(path.name.lower()) or content.get(path.stem.lower())
        if transcript is None:
            raise RuntimeError(f"missing transcript for {path}")
        info = _audio_info(path)
        if info["sample_rate"] != 44_100 or info["subtype"] != "PCM_16":
            raise RuntimeError(f"unexpected official source format for {path}: {info}")
        clips.append(
            {
                "utterance_id": transcript["utterance_id"],
                "text": transcript["text"],
                "path": path.resolve(),
                **info,
            }
        )
    if len(clips) < 4:
        raise RuntimeError(f"not enough WAVs for {speaker_id}: {len(clips)}")
    return sorted(clips, key=lambda item: (-item["duration_seconds"], item["utterance_id"]))


def _select_clip_group(
    clips: Sequence[dict[str, Any]],
    *,
    excluded_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    excluded = set(excluded_ids)
    pool = [item for item in clips if item["utterance_id"] not in excluded]
    best: tuple[tuple[Any, ...], tuple[dict[str, Any], ...]] | None = None

    def consider(group: tuple[dict[str, Any], ...]) -> None:
        nonlocal best
        source_duration = sum(item["duration_seconds"] for item in group)
        duration = source_duration + REFERENCE_GAP_SECONDS * (len(group) - 1)
        if not REFERENCE_MIN_SECONDS <= duration <= REFERENCE_MAX_SECONDS:
            return
        score = (
            abs(duration - REFERENCE_TARGET_SECONDS),
            -source_duration,
            len(group),
            tuple(sorted(item["utterance_id"] for item in group)),
        )
        candidate = (score, group)
        if best is None or candidate[0] < best[0]:
            best = candidate

    # Pairs are cheap enough to inspect exhaustively and cover the common case.
    for group in itertools.combinations(pool, 2):
        consider(group)

    # Exhaustive triples are O(n^3) for roughly 400-500 clips per speaker.
    # For each first/second pair, binary-search the third duration nearest the
    # 10-second target. Neighbors around the insertion point cover rounding and
    # duplicate-duration ties while keeping selection O(n^2 log n).
    ascending = sorted(
        pool, key=lambda item: (item["duration_seconds"], item["utterance_id"])
    )
    durations = [item["duration_seconds"] for item in ascending]
    for first in range(max(0, len(ascending) - 2)):
        for second in range(first + 1, len(ascending) - 1):
            desired = (
                REFERENCE_TARGET_SECONDS
                - 2 * REFERENCE_GAP_SECONDS
                - durations[first]
                - durations[second]
            )
            insertion = bisect.bisect_left(
                durations, desired, lo=second + 1
            )
            for third in range(
                max(second + 1, insertion - 2),
                min(len(ascending), insertion + 3),
            ):
                consider((ascending[first], ascending[second], ascending[third]))

    if best is None:
        preview = [
            (item["utterance_id"], item["duration_seconds"])
            for item in sorted(
                pool,
                key=lambda item: (-item["duration_seconds"], item["utterance_id"]),
            )[:8]
        ]
        raise RuntimeError(
            "could not form a 2-3 clip reference between 8 and 12 seconds; "
            f"longest candidates={preview}"
        )
    selected = best[1]
    return sorted(selected, key=lambda item: item["utterance_id"])


def _prepare_clip_group(
    dataset_root: Path,
    clips: Sequence[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    gap = np.zeros(round(SAMPLE_RATE * REFERENCE_GAP_SECONDS), dtype=np.float32)
    audio_parts: list[np.ndarray] = []
    sources: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        source_path = Path(clip["path"])
        values = _read_audio_24k(source_path)
        if index:
            audio_parts.append(gap)
        audio_parts.append(values)
        sources.append(
            {
                "utterance_id": clip["utterance_id"],
                "relative_path": source_path.relative_to(dataset_root).as_posix(),
                "text": clip["text"],
                "duration_seconds": clip["duration_seconds"],
                "sample_rate": clip["sample_rate"],
                "channels": clip["channels"],
                "subtype": clip["subtype"],
                "bytes": source_path.stat().st_size,
                "sha256": _sha256(source_path),
            }
        )
    combined = np.concatenate(audio_parts).astype(np.float32, copy=False)
    if not REFERENCE_MIN_SECONDS <= len(combined) / SAMPLE_RATE <= REFERENCE_MAX_SECONDS:
        raise RuntimeError(
            f"prepared reference duration escaped 8-12 s: {len(combined) / SAMPLE_RATE}"
        )
    prepared = _write_pcm16_wav(output_path, combined)
    return {
        "source_clips": sources,
        "transcript": "，".join(item["text"] for item in sources),
        "prepared_wav": prepared,
    }


def _hash_cache_key(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (int(stat.st_dev), int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns))


def _model_fingerprint(
    model_dir: Path,
    hash_cache: dict[tuple[int, int, int, int], str] | None = None,
) -> dict[str, Any]:
    root = model_dir.resolve(strict=True)
    relative_files = list(MODEL_CORE_FILES)
    embeddings = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "embeddings").glob("*.npy")
        if path.is_file()
    )
    if not embeddings:
        raise RuntimeError(f"model has no embedding assets: {root}")
    relative_files.extend(embeddings)
    records: list[dict[str, Any]] = []
    for relative in relative_files:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"missing runtime model artifact: {path}")
        cache_key = _hash_cache_key(path)
        digest = hash_cache.get(cache_key) if hash_cache is not None else None
        if digest is None:
            print(f"CLONE_BLIND_A_HASH_MODEL={path}", flush=True)
            digest = _sha256(path)
            if hash_cache is not None:
                hash_cache[cache_key] = digest
        records.append(
            {"relative_path": relative, "bytes": path.stat().st_size, "sha256": digest}
        )
    return {
        "model_dir": str(root),
        "files": records,
        "fingerprint_sha256": _canonical_digest(records),
    }


def _code_fingerprint(probe_root: Path) -> dict[str, Any]:
    root = probe_root.resolve(strict=True)
    package_root = root / "qwen3_tts_gguf"
    files = sorted(package_root.rglob("*.py"))
    if not files:
        raise RuntimeError(f"probe package has no Python sources: {package_root}")
    records = [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]
    return {
        "probe_root": str(root),
        "files": records,
        "fingerprint_sha256": _canonical_digest(records),
    }


def _runner_fingerprint() -> dict[str, Any]:
    path = Path(__file__).resolve(strict=True)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _files_by_name(fingerprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["relative_path"]: item for item in fingerprint["files"]}


def _single_variable_contract(
    base: dict[str, Any], custom: dict[str, Any]
) -> dict[str, Any]:
    base_files = _files_by_name(base)
    custom_files = _files_by_name(custom)
    shared: dict[str, str] = {}
    for relative in SINGLE_VARIABLE_FILES:
        base_hash = base_files[relative]["sha256"]
        custom_hash = custom_files[relative]["sha256"]
        if base_hash != custom_hash:
            raise RuntimeError(
                f"single-variable contract failed; {relative} differs: "
                f"base={base_hash} custom_voice={custom_hash}"
            )
        shared[relative] = base_hash
    varying = [
        relative
        for relative in (
            "qwen3_tts_talker.q5_k.gguf",
            "qwen3_tts_predictor.q8_0.gguf",
        )
        if base_files[relative]["sha256"] != custom_files[relative]["sha256"]
    ]
    if not varying:
        raise RuntimeError("Base and CustomVoice talker/predictor artifacts are identical")
    return {
        "passed": True,
        "identical_codec_speaker_decoder_and_tokenizer": shared,
        "differing_primary_artifacts": varying,
        "interpretation": "arms differ in talker/predictor/embeddings, not encoders",
    }


def _verify_fingerprint(fingerprint: dict[str, Any]) -> None:
    root_key = "model_dir" if "model_dir" in fingerprint else "probe_root"
    root = Path(fingerprint[root_key]).resolve(strict=True)
    current: list[dict[str, Any]] = []
    for expected in fingerprint["files"]:
        path = root / expected["relative_path"]
        if not path.is_file():
            raise RuntimeError(f"frozen runtime artifact is missing: {path}")
        actual = {
            "relative_path": expected["relative_path"],
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if actual != expected:
            raise RuntimeError(
                f"frozen runtime artifact changed: {path}: "
                f"expected={expected} actual={actual}"
            )
        current.append(actual)
    if _canonical_digest(current) != fingerprint["fingerprint_sha256"]:
        raise RuntimeError(f"runtime fingerprint mismatch below {root}")


def _random_label(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(4)


def _new_mapping(manifest: dict[str, Any]) -> dict[str, Any]:
    arms = ["base", "custom_voice"]
    generation_order = list(arms)
    secrets.SystemRandom().shuffle(generation_order)
    speaker_order = [item["speaker_slot"] for item in manifest["speakers"]]
    secrets.SystemRandom().shuffle(speaker_order)

    trials: dict[str, dict[str, Any]] = {}
    presentation_order: list[str] = []
    for speaker in manifest["speakers"]:
        trial_id = _random_label("trial")
        labels = [_random_label("sample"), _random_label("sample")]
        sources = list(arms)
        secrets.SystemRandom().shuffle(sources)
        candidate_order = list(labels)
        secrets.SystemRandom().shuffle(candidate_order)
        trials[trial_id] = {
            "kind": "primary",
            "speaker_slot": speaker["speaker_slot"],
            "speaker_id": speaker["speaker_id"],
            "label_to_source": dict(zip(labels, sources, strict=True)),
            "candidate_order": candidate_order,
        }
        presentation_order.append(trial_id)

    catch_speaker = next(
        item
        for item in manifest["speakers"]
        if item["speaker_id"] == manifest["catch_trial"]["speaker_id"]
    )
    catch_trial_id = _random_label("trial")
    catch_labels = [_random_label("sample"), _random_label("sample")]
    catch_synthetic_arm = secrets.choice(arms)
    catch_sources = ["real_recording", catch_synthetic_arm]
    secrets.SystemRandom().shuffle(catch_sources)
    catch_candidate_order = list(catch_labels)
    secrets.SystemRandom().shuffle(catch_candidate_order)
    trials[catch_trial_id] = {
        "kind": "catch",
        "speaker_slot": catch_speaker["speaker_slot"],
        "speaker_id": catch_speaker["speaker_id"],
        "label_to_source": dict(zip(catch_labels, catch_sources, strict=True)),
        "candidate_order": catch_candidate_order,
        "synthetic_arm": catch_synthetic_arm,
    }
    presentation_order.append(catch_trial_id)
    secrets.SystemRandom().shuffle(presentation_order)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "created_utc": _utc_now(),
        "preregistration_sha256": manifest["preregistration_sha256"],
        "generation_arm_order": generation_order,
        "speaker_generation_order": speaker_order,
        "presentation_order": presentation_order,
        "trials": trials,
    }


def _write_listening_shell(
    listen_dir: Path,
    sealed_dir: Path,
    manifest: dict[str, Any],
    mapping: dict[str, Any],
) -> None:
    speaker_by_slot = {item["speaker_slot"]: item for item in manifest["speakers"]}
    public_trials: list[dict[str, Any]] = []
    rating_trials: list[dict[str, Any]] = []
    for trial_id in mapping["presentation_order"]:
        trial = mapping["trials"][trial_id]
        trial_dir = listen_dir / trial_id
        trial_dir.mkdir(parents=True, exist_ok=False)
        speaker = speaker_by_slot[trial["speaker_slot"]]
        prepared_ref = sealed_dir / speaker["reference"]["prepared_wav"]["relative_path"]
        public_ref = trial_dir / "reference.wav"
        shutil.copy2(prepared_ref, public_ref)
        labels = trial["candidate_order"]
        public_trials.append(
            {
                "trial_id": trial_id,
                "reference_file": f"{trial_id}/reference.wav",
                "candidate_files": {
                    label: f"{trial_id}/{label}.wav" for label in labels
                },
                "candidate_order": labels,
            }
        )
        rating_trials.append(
            {
                "trial_id": trial_id,
                "more_similar_to_reference": None,
                "candidate_scores": {
                    label: {
                        "naturalness_1_to_5": None,
                        "stability_1_to_5": None,
                    }
                    for label in labels
                },
                "notes": "",
            }
        )

    blind_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "awaiting_generation",
        "run_id": manifest["run_id"],
        "purpose": "Sealed Base versus CustomVoice clone test with one catch trial.",
        "preregistration_sha256": manifest["preregistration_sha256"],
        "trial_count": len(public_trials),
        "primary_trial_count": 8,
        "catch_trial_count": 1,
        "trials": public_trials,
    }
    _write_json(listen_dir / "blind_manifest.json", blind_manifest)
    _write_json(
        listen_dir / "ratings_template.json",
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": manifest["run_id"],
            "preregistration_sha256": manifest["preregistration_sha256"],
            "instructions": (
                "For every trial, choose exactly one candidate label as more similar "
                "to reference, then score both candidates for naturalness and stability."
            ),
            "trials": rating_trials,
        },
    )
    instructions = [
        "# Clone blind test A",
        "",
        "Do not inspect the sibling `sealed/` directory or file hashes before rating.",
        "The listening set contains eight Base-vs-CustomVoice trials and one hidden catch trial.",
        "For each trial, listen to `reference.wav`, then both randomly named candidates.",
        "Choose exactly one candidate as more similar to the reference speaker.",
        "Also score each candidate's naturalness and stability from 1 to 5.",
        "Do not rate resemblance to any known or famous person.",
        "",
        "Fill `ratings_template.json`, then run the score command exactly once to reveal.",
        "",
    ]
    for trial in public_trials:
        instructions.append(f"- [{trial['trial_id']}]({trial['trial_id']}/reference.wav)")
    (listen_dir / "BLIND_LISTENING.md").write_text(
        "\n".join(instructions) + "\n", encoding="utf-8"
    )


def _prepare(args: argparse.Namespace) -> None:
    _assert_private_roots()
    run_id = _validate_run_id(args.run_id or _new_run_id())
    listen_dir = LISTEN_ROOT / run_id
    sealed_dir = SEALED_ROOT / run_id
    if listen_dir.exists() or sealed_dir.exists():
        raise RuntimeError(f"run already exists: {run_id}")

    archive = args.archive.resolve(strict=True)
    if archive.name != OFFICIAL_ARCHIVE_NAME:
        raise RuntimeError(
            f"formal blind test requires the official {OFFICIAL_ARCHIVE_NAME}, got {archive.name}"
        )
    print(f"CLONE_BLIND_A_HASH_ARCHIVE={archive}", flush=True)
    archive_hashes = _file_hashes(archive, ("md5", "sha256"))
    if archive_hashes["md5"].lower() != OFFICIAL_ARCHIVE_MD5:
        raise RuntimeError(
            f"official AISHELL-3 MD5 mismatch: expected={OFFICIAL_ARCHIVE_MD5} "
            f"actual={archive_hashes['md5']}"
        )

    dataset_root = _resolve_dataset_root(args.dataset_root)
    speaker_info_path = dataset_root / "spk-info.txt"
    content_path = dataset_root / "train" / "content.txt"
    speaker_info = _parse_speaker_info(speaker_info_path)
    content = _parse_content(content_path)
    speaker_ids = list(args.speaker_id)
    missing_speakers = [item for item in speaker_ids if item not in speaker_info]
    if missing_speakers:
        raise RuntimeError(f"speaker IDs absent from spk-info.txt: {missing_speakers}")
    selected_metadata = [speaker_info[item] for item in speaker_ids]
    balance = _validate_speaker_balance(selected_metadata)
    catch_speaker_id = args.catch_speaker_id or secrets.choice(speaker_ids)
    if catch_speaker_id not in speaker_ids:
        raise RuntimeError("catch speaker must be one of the eight selected speakers")

    probe_root = args.probe_root.resolve(strict=True)
    hash_cache: dict[tuple[int, int, int, int], str] = {}
    base_fingerprint = _model_fingerprint(args.base_model_dir, hash_cache)
    custom_fingerprint = _model_fingerprint(args.custom_model_dir, hash_cache)
    single_variable = _single_variable_contract(base_fingerprint, custom_fingerprint)
    probe_fingerprint = _code_fingerprint(probe_root)

    sealed_dir.mkdir(parents=True, exist_ok=False)
    listen_dir.mkdir(parents=True, exist_ok=False)
    prepared_dir = sealed_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=False)

    speakers: list[dict[str, Any]] = []
    for index, speaker_id in enumerate(speaker_ids, start=1):
        print(f"CLONE_BLIND_A_PREPARE_SPEAKER={index}/8", flush=True)
        clips = _speaker_clips(dataset_root, speaker_id, content)
        reference_clips = _select_clip_group(clips)
        slot = f"speaker_{index:02d}"
        reference_path = prepared_dir / f"{slot}_reference.wav"
        reference = _prepare_clip_group(dataset_root, reference_clips, reference_path)
        reference["prepared_wav"]["relative_path"] = reference_path.relative_to(
            sealed_dir
        ).as_posix()
        reference["prepared_wav"].pop("path", None)
        speaker_record: dict[str, Any] = {
            "speaker_slot": slot,
            **speaker_info[speaker_id],
            "reference": reference,
        }
        if speaker_id == catch_speaker_id:
            catch_clips = _select_clip_group(
                clips,
                excluded_ids=[item["utterance_id"] for item in reference_clips],
            )
            catch_path = prepared_dir / f"{slot}_catch_real.wav"
            catch_audio = _prepare_clip_group(dataset_root, catch_clips, catch_path)
            catch_audio["prepared_wav"]["relative_path"] = catch_path.relative_to(
                sealed_dir
            ).as_posix()
            catch_audio["prepared_wav"].pop("path", None)
            speaker_record["catch_real_recording"] = catch_audio
        speakers.append(speaker_record)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "frozen_before_generation",
        "run_id": run_id,
        "created_utc": _utc_now(),
        "purpose": "Decide whether the Base model earns its approximately 1.92 GiB package cost.",
        "decision_rule": DECISION_RULE,
        "source": {
            "dataset": "AISHELL-3",
            "official_source_url": OFFICIAL_SOURCE_URL,
            "license": "Apache-2.0",
            "archive": {
                "path": str(archive),
                "bytes": archive.stat().st_size,
                "official_md5": OFFICIAL_ARCHIVE_MD5,
                **archive_hashes,
            },
            "dataset_root": str(dataset_root),
            "spk_info": {
                "path": str(speaker_info_path),
                "sha256": _sha256(speaker_info_path),
            },
            "train_content": {
                "path": str(content_path),
                "sha256": _sha256(content_path),
            },
        },
        "preparation": {
            "output_sample_rate": SAMPLE_RATE,
            "channels": 1,
            "subtype": "PCM_16",
            "reference_seconds": [REFERENCE_MIN_SECONDS, REFERENCE_MAX_SECONDS],
            "clips_per_reference": [2, 3],
            "inter_clip_silence_seconds": REFERENCE_GAP_SECONDS,
            "selection_policy": (
                "best 2-3 clip combination between 8 and 12 seconds, closest to 10 seconds; "
                "ties prefer longer source audio then stable utterance IDs"
            ),
        },
        "speaker_selection": {
            "speaker_count": 8,
            "balance": balance,
            "selection_note": args.selection_note,
        },
        "speakers": speakers,
        "targets": {
            "primary": list(TARGET_TEXTS),
            "catch": CATCH_TARGET_TEXT,
            "language": "chinese",
        },
        "catch_trial": {
            "speaker_id": catch_speaker_id,
            "is_additional_to_primary_trials": True,
            "failure_action": DECISION_RULE["catch_failure"],
        },
        "generation": {
            "config": dict(GENERATION_CONFIG),
            "stream_n_ctx": STREAM_N_CTX,
            "onnx_provider": args.onnx_provider,
            "llm_use_gpu": args.llm_use_gpu,
            "zero_shot": False,
            "independent_reference_encoding_per_arm": True,
            "models": {
                "base": base_fingerprint,
                "custom_voice": custom_fingerprint,
            },
            "probe_code": probe_fingerprint,
        },
        "runner_code": _runner_fingerprint(),
        "single_variable_contract": single_variable,
    }
    manifest_path = sealed_dir / "preregistration_manifest.json"
    _write_json(manifest_path, manifest)
    preregistration_sha256 = _sha256(manifest_path)
    manifest["preregistration_sha256"] = preregistration_sha256
    # The hash anchors the exact file without a self-referential field. Keep it
    # in the sidecar and in downstream artifacts, not inside the hashed file.
    _write_hash_sidecar(
        sealed_dir / "preregistration_manifest.sha256", preregistration_sha256
    )

    mapping = _new_mapping(manifest)
    mapping_path = sealed_dir / "arm_mapping.json"
    _write_json(mapping_path, mapping)
    mapping_sha256 = _sha256(mapping_path)
    _write_hash_sidecar(sealed_dir / "arm_mapping.sha256", mapping_sha256)
    _write_listening_shell(listen_dir, sealed_dir, manifest, mapping)
    _write_json(
        sealed_dir / "prepare_report.json",
        {
            "status": "prepared",
            "run_id": run_id,
            "created_utc": _utc_now(),
            "preregistration_manifest": str(manifest_path),
            "preregistration_sha256": preregistration_sha256,
            "arm_mapping": str(mapping_path),
            "arm_mapping_sha256": mapping_sha256,
            "listen_dir": str(listen_dir),
        },
    )
    print("CLONE_BLIND_A_STATUS=prepared", flush=True)
    print(f"CLONE_BLIND_A_RUN_ID={run_id}", flush=True)
    print(f"CLONE_BLIND_A_PREREGISTRATION={manifest_path}", flush=True)
    print(f"CLONE_BLIND_A_PREREGISTRATION_SHA256={preregistration_sha256}", flush=True)
    print(f"CLONE_BLIND_A_MAPPING_SHA256={mapping_sha256}", flush=True)
    print(
        f"CLONE_BLIND_A_NEXT=python tests/run_clone_blind_a.py generate --run-id {run_id}",
        flush=True,
    )


def _load_frozen_run(run_id: str) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    _assert_private_roots()
    run_id = _validate_run_id(run_id)
    sealed_dir = SEALED_ROOT / run_id
    listen_dir = LISTEN_ROOT / run_id
    manifest_path = sealed_dir / "preregistration_manifest.json"
    mapping_path = sealed_dir / "arm_mapping.json"
    expected_manifest_hash = _read_hash_sidecar(
        sealed_dir / "preregistration_manifest.sha256"
    )
    actual_manifest_hash = _sha256(manifest_path)
    if actual_manifest_hash != expected_manifest_hash:
        raise RuntimeError(
            "preregistration manifest changed after freezing: "
            f"expected={expected_manifest_hash} actual={actual_manifest_hash}"
        )
    expected_mapping_hash = _read_hash_sidecar(sealed_dir / "arm_mapping.sha256")
    actual_mapping_hash = _sha256(mapping_path)
    if actual_mapping_hash != expected_mapping_hash:
        raise RuntimeError(
            f"sealed arm mapping changed: expected={expected_mapping_hash} "
            f"actual={actual_mapping_hash}"
        )
    manifest = _read_json(manifest_path)
    mapping = _read_json(mapping_path)
    if manifest["run_id"] != run_id or mapping["run_id"] != run_id:
        raise RuntimeError("run ID mismatch in sealed artifacts")
    if mapping["preregistration_sha256"] != expected_manifest_hash:
        raise RuntimeError("arm mapping points to a different preregistration manifest")
    manifest["preregistration_sha256"] = expected_manifest_hash
    return sealed_dir, listen_dir, manifest, mapping


def _verify_prepared_audio(sealed_dir: Path, manifest: dict[str, Any]) -> None:
    for speaker in manifest["speakers"]:
        records = [speaker["reference"]]
        if "catch_real_recording" in speaker:
            records.append(speaker["catch_real_recording"])
        for record in records:
            expected = record["prepared_wav"]
            path = sealed_dir / expected["relative_path"]
            if not path.is_file():
                raise RuntimeError(f"prepared audio is missing: {path}")
            if path.stat().st_size != expected["bytes"] or _sha256(path) != expected["sha256"]:
                raise RuntimeError(f"prepared audio changed after freezing: {path}")
            info = _audio_info(path)
            if info != expected["audio_format"]:
                raise RuntimeError(f"prepared audio format changed: {path}")


def _verify_runner_fingerprint(manifest: dict[str, Any]) -> None:
    expected = manifest.get("runner_code")
    if expected is None:
        return
    path = Path(expected["path"]).resolve(strict=True)
    actual = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if actual != expected:
        raise RuntimeError(
            f"blind-test runner changed after preregistration: expected={expected} actual={actual}"
        )


def _result_record(result: Any, output_path: Path) -> dict[str, Any]:
    if result is None or getattr(result, "audio", None) is None:
        raise RuntimeError("clone returned no audio")
    codes = getattr(result, "codes", None)
    if codes is None or len(codes) == 0:
        raise RuntimeError("clone returned no codec tokens")
    record = _write_pcm16_wav(output_path, np.asarray(result.audio, dtype=np.float32))
    record["codes_shape"] = list(np.asarray(codes).shape)
    record["relative_path"] = output_path.as_posix()
    record.pop("path", None)
    return record


def _materialize_candidates(
    sealed_dir: Path,
    listen_dir: Path,
    manifest: dict[str, Any],
    mapping: dict[str, Any],
    report: dict[str, Any],
) -> None:
    speaker_by_slot = {item["speaker_slot"]: item for item in manifest["speakers"]}
    blind_path = listen_dir / "blind_manifest.json"
    blind = _read_json(blind_path)
    public_by_id = {item["trial_id"]: item for item in blind["trials"]}
    for trial_id in mapping["presentation_order"]:
        trial = mapping["trials"][trial_id]
        public_trial = public_by_id[trial_id]
        speaker = speaker_by_slot[trial["speaker_slot"]]
        candidate_records: dict[str, Any] = {}
        for label in trial["candidate_order"]:
            source = trial["label_to_source"][label]
            destination = listen_dir / trial_id / f"{label}.wav"
            if trial["kind"] == "primary":
                source_records = report["arms"][source][trial["speaker_slot"]]["targets"]
                source_paths = [
                    sealed_dir / item["relative_path"] for item in source_records
                ]
                combined = _join_wavs(source_paths, OUTPUT_GAP_SECONDS)
                record = _write_pcm16_wav(destination, combined)
            elif source == "real_recording":
                source_record = speaker["catch_real_recording"]["prepared_wav"]
                shutil.copy2(sealed_dir / source_record["relative_path"], destination)
                record = {
                    **_audio_metrics(_read_audio_24k(destination)),
                    "path": str(destination),
                    "bytes": destination.stat().st_size,
                    "sha256": _sha256(destination),
                    "audio_format": _audio_info(destination),
                }
            else:
                source_record = report["arms"][source][trial["speaker_slot"]]["catch"]
                shutil.copy2(sealed_dir / source_record["relative_path"], destination)
                record = {
                    **_audio_metrics(_read_audio_24k(destination)),
                    "path": str(destination),
                    "bytes": destination.stat().st_size,
                    "sha256": _sha256(destination),
                    "audio_format": _audio_info(destination),
                }
            record["relative_path"] = destination.relative_to(listen_dir).as_posix()
            record.pop("path", None)
            candidate_records[label] = record
        reference_path = listen_dir / public_trial["reference_file"]
        public_trial["reference"] = {
            "relative_path": public_trial["reference_file"],
            "bytes": reference_path.stat().st_size,
            "sha256": _sha256(reference_path),
            "audio_format": _audio_info(reference_path),
        }
        public_trial["candidates"] = candidate_records
    blind["status"] = "ready_for_rating"
    blind["generated_utc"] = _utc_now()
    _write_json(blind_path, blind)


def _generate(args: argparse.Namespace) -> None:
    sealed_dir, listen_dir, manifest, mapping = _load_frozen_run(args.run_id)
    existing_report = sealed_dir / "generation_report.json"
    if existing_report.is_file() and _read_json(existing_report).get("status") == "passed":
        raise RuntimeError(f"generation already passed for run {args.run_id}")

    _verify_prepared_audio(sealed_dir, manifest)
    _verify_runner_fingerprint(manifest)
    for fingerprint in manifest["generation"]["models"].values():
        _verify_fingerprint(fingerprint)
    _verify_fingerprint(manifest["generation"]["probe_code"])

    probe_root = Path(manifest["generation"]["probe_code"]["probe_root"]).resolve()
    old_cwd = Path.cwd()
    if str(probe_root) not in sys.path:
        sys.path.insert(0, str(probe_root))
    os.chdir(probe_root)
    import qwen3_tts_gguf
    from qwen3_tts_gguf.inference import TTSEngine, TTSConfig

    package_path = Path(qwen3_tts_gguf.__file__).resolve()
    if not _is_relative_to(package_path, probe_root):
        raise RuntimeError(f"GGUF runtime source mismatch: {package_path}")

    speaker_by_slot = {item["speaker_slot"]: item for item in manifest["speakers"]}
    generated_root = sealed_dir / "generated"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "started",
        "run_id": args.run_id,
        "started_utc": _utc_now(),
        "preregistration_sha256": manifest["preregistration_sha256"],
        "package_file": str(package_path),
        "independent_reference_encoding_per_arm": True,
        "arms": {},
    }
    try:
        for arm in mapping["generation_arm_order"]:
            print(f"CLONE_BLIND_A_GENERATE_ARM={arm}", flush=True)
            model_dir = manifest["generation"]["models"][arm]["model_dir"]
            engine = None
            arm_started = time.perf_counter()
            arm_report: dict[str, Any] = {}
            try:
                engine = TTSEngine(
                    model_dir=model_dir,
                    onnx_provider=manifest["generation"]["onnx_provider"],
                    llm_use_gpu=manifest["generation"]["llm_use_gpu"],
                    verbose=True,
                )
                if not engine or not engine.ready:
                    raise RuntimeError(f"{arm} TTSEngine did not become ready")
                if engine.codec_encoder is None or engine.speaker_encoder is None:
                    raise RuntimeError(f"{arm} did not load the shared encoder pair")
                stream = engine.create_stream(n_ctx=manifest["generation"]["stream_n_ctx"])
                if stream is None:
                    raise RuntimeError(f"{arm} stream creation failed")

                for position, slot in enumerate(
                    mapping["speaker_generation_order"], start=1
                ):
                    print(
                        f"CLONE_BLIND_A_GENERATE_SPEAKER={arm}:{position}/8",
                        flush=True,
                    )
                    speaker = speaker_by_slot[slot]
                    ref_record = speaker["reference"]["prepared_wav"]
                    ref_path = sealed_dir / ref_record["relative_path"]
                    anchor_started = time.perf_counter()
                    anchor = stream.set_voice(
                        ref_path,
                        text=speaker["reference"]["transcript"],
                    )
                    if not anchor:
                        raise RuntimeError(f"{arm} set_voice failed for {slot}")
                    if getattr(anchor, "spk_emb", None) is None:
                        raise RuntimeError(f"{arm} produced no speaker embedding for {slot}")
                    if tuple(np.asarray(anchor.spk_emb).shape) != (2048,):
                        raise RuntimeError(
                            f"{arm} unexpected speaker embedding for {slot}: "
                            f"{np.asarray(anchor.spk_emb).shape}"
                        )
                    if getattr(anchor, "final_state", None) is None:
                        raise RuntimeError(f"{arm} full-ICL anchor has no final_state for {slot}")
                    anchor_elapsed_seconds = round(
                        time.perf_counter() - anchor_started, 6
                    )

                    slot_dir = generated_root / arm / slot
                    target_records: list[dict[str, Any]] = []
                    for target_index, text in enumerate(
                        manifest["targets"]["primary"], start=1
                    ):
                        started = time.perf_counter()
                        result = stream.clone(
                            text=text,
                            language=manifest["targets"]["language"],
                            zero_shot=False,
                            config=TTSConfig(**manifest["generation"]["config"]),
                        )
                        path = slot_dir / f"target_{target_index:02d}.wav"
                        record = _result_record(result, path)
                        record["relative_path"] = path.relative_to(sealed_dir).as_posix()
                        record["target_index"] = target_index
                        record["text"] = text
                        record["elapsed_seconds"] = round(
                            time.perf_counter() - started, 6
                        )
                        target_records.append(record)
                    slot_report: dict[str, Any] = {
                        "anchor_elapsed_seconds": anchor_elapsed_seconds,
                        "reference_sha256": ref_record["sha256"],
                        "anchor_codes_shape": list(np.asarray(anchor.codes).shape),
                        "anchor_spk_emb_shape": list(np.asarray(anchor.spk_emb).shape),
                        "anchor_has_final_state": True,
                        "targets": target_records,
                    }
                    catch_trial = next(
                        trial
                        for trial in mapping["trials"].values()
                        if trial["kind"] == "catch"
                    )
                    if (
                        catch_trial["speaker_slot"] == slot
                        and catch_trial["synthetic_arm"] == arm
                    ):
                        started = time.perf_counter()
                        catch_result = stream.clone(
                            text=manifest["targets"]["catch"],
                            language=manifest["targets"]["language"],
                            zero_shot=False,
                            config=TTSConfig(**manifest["generation"]["config"]),
                        )
                        catch_path = slot_dir / "catch.wav"
                        catch_record = _result_record(catch_result, catch_path)
                        catch_record["relative_path"] = catch_path.relative_to(
                            sealed_dir
                        ).as_posix()
                        catch_record["text"] = manifest["targets"]["catch"]
                        catch_record["elapsed_seconds"] = round(
                            time.perf_counter() - started, 6
                        )
                        slot_report["catch"] = catch_record
                    arm_report[slot] = slot_report
            finally:
                if engine is not None:
                    engine.shutdown()
            report["arms"][arm] = arm_report
            report.setdefault("arm_elapsed_seconds", {})[arm] = round(
                time.perf_counter() - arm_started, 6
            )

        _materialize_candidates(sealed_dir, listen_dir, manifest, mapping, report)
        report["status"] = "passed"
        report["finished_utc"] = _utc_now()
        report["listen_dir"] = str(listen_dir)
    except BaseException as exc:
        report["status"] = "failed"
        report["finished_utc"] = _utc_now()
        report["error"] = repr(exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        os.chdir(old_cwd)
        _write_json(existing_report, report)
        print(f"CLONE_BLIND_A_STATUS={report['status']}", flush=True)
        print(f"CLONE_BLIND_A_GENERATION_REPORT={existing_report}", flush=True)
        print(f"CLONE_BLIND_A_GENERATION_REPORT_SHA256={_sha256(existing_report)}", flush=True)


def _verify_public_audio(listen_dir: Path, blind: dict[str, Any]) -> None:
    if blind.get("status") != "ready_for_rating":
        raise RuntimeError("listening set is not ready for rating")
    for trial in blind["trials"]:
        records = [trial["reference"], *trial["candidates"].values()]
        for record in records:
            path = listen_dir / record["relative_path"]
            if not path.is_file():
                raise RuntimeError(f"listening file is missing: {path}")
            if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
                raise RuntimeError(f"listening file changed after generation: {path}")


def _validate_rating_value(value: Any, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{description} must be a number from 1 to 5")
    number = float(value)
    if not 1.0 <= number <= 5.0:
        raise RuntimeError(f"{description} must be between 1 and 5")
    return number


def _decision_for_counts(
    *, catch_passed: bool, base_wins: int, custom_wins: int
) -> tuple[str, str]:
    if base_wins + custom_wins != 8:
        raise RuntimeError("decision requires exactly eight primary results")
    if not catch_passed:
        return "invalid_repeat", DECISION_RULE["catch_failure"]
    if base_wins >= 6:
        return "retain_base", DECISION_RULE["retain_base"]
    return "delete_base", DECISION_RULE["delete_base"]


def _score(args: argparse.Namespace) -> None:
    sealed_dir, listen_dir, manifest, mapping = _load_frozen_run(args.run_id)
    _verify_runner_fingerprint(manifest)
    generation_report = _read_json(sealed_dir / "generation_report.json")
    if generation_report.get("status") != "passed":
        raise RuntimeError("generation has not passed")
    score_path = sealed_dir / "score_report.json"
    if score_path.exists():
        raise RuntimeError(
            "this run has already been revealed; do not edit thresholds or ratings after reveal"
        )
    blind = _read_json(listen_dir / "blind_manifest.json")
    _verify_public_audio(listen_dir, blind)
    ratings_path = (
        args.ratings.resolve(strict=True)
        if args.ratings
        else listen_dir / "ratings_template.json"
    )
    ratings = _read_json(ratings_path)
    if ratings.get("run_id") != args.run_id:
        raise RuntimeError("ratings belong to a different run")
    if ratings.get("preregistration_sha256") != manifest["preregistration_sha256"]:
        raise RuntimeError("ratings point to a different preregistration manifest")

    rating_by_trial = {item["trial_id"]: item for item in ratings["trials"]}
    if set(rating_by_trial) != set(mapping["trials"]):
        raise RuntimeError("ratings trial set does not match the sealed mapping")
    base_wins = 0
    custom_wins = 0
    catch_passed = False
    primary_results: list[dict[str, Any]] = []
    metric_values: dict[str, dict[str, list[float]]] = {}
    for trial_id in mapping["presentation_order"]:
        trial = mapping["trials"][trial_id]
        rating = rating_by_trial[trial_id]
        labels = set(trial["label_to_source"])
        choice = rating.get("more_similar_to_reference")
        if choice not in labels:
            raise RuntimeError(f"{trial_id} must choose exactly one candidate label")
        candidate_scores = rating.get("candidate_scores", {})
        if set(candidate_scores) != labels:
            raise RuntimeError(f"{trial_id} candidate score labels do not match")
        for label, values in candidate_scores.items():
            source = trial["label_to_source"][label]
            bucket = metric_values.setdefault(
                source, {"naturalness": [], "stability": []}
            )
            bucket["naturalness"].append(
                _validate_rating_value(
                    values.get("naturalness_1_to_5"),
                    f"{trial_id}/{label} naturalness",
                )
            )
            bucket["stability"].append(
                _validate_rating_value(
                    values.get("stability_1_to_5"),
                    f"{trial_id}/{label} stability",
                )
            )
        chosen_source = trial["label_to_source"][choice]
        if trial["kind"] == "catch":
            catch_passed = chosen_source == "real_recording"
        else:
            if chosen_source == "base":
                base_wins += 1
            elif chosen_source == "custom_voice":
                custom_wins += 1
            else:
                raise RuntimeError(f"unexpected primary source: {chosen_source}")
            primary_results.append(
                {
                    "trial_id": trial_id,
                    "speaker_id": trial["speaker_id"],
                    "winner": chosen_source,
                }
            )
    if len(primary_results) != 8 or base_wins + custom_wins != 8:
        raise RuntimeError("decision requires exactly eight completed primary trials")

    averages = {
        source: {
            metric: round(sum(values) / len(values), 6)
            for metric, values in metrics.items()
        }
        for source, metrics in metric_values.items()
    }
    decision, rationale = _decision_for_counts(
        catch_passed=catch_passed,
        base_wins=base_wins,
        custom_wins=custom_wins,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "revealed",
        "run_id": args.run_id,
        "revealed_utc": _utc_now(),
        "preregistration_sha256": manifest["preregistration_sha256"],
        "arm_mapping_sha256": _sha256(sealed_dir / "arm_mapping.json"),
        "ratings_path": str(ratings_path),
        "ratings_sha256": _sha256(ratings_path),
        "catch_passed": catch_passed,
        "base_wins": base_wins,
        "custom_voice_wins": custom_wins,
        "decision": decision,
        "rationale": rationale,
        "primary_results": primary_results,
        "mean_scores_by_source": averages,
    }
    _write_json(score_path, report)
    print("CLONE_BLIND_A_STATUS=revealed", flush=True)
    print(f"CLONE_BLIND_A_CATCH_PASSED={str(catch_passed).lower()}", flush=True)
    print(f"CLONE_BLIND_A_BASE_WINS={base_wins}/8", flush=True)
    print(f"CLONE_BLIND_A_DECISION={decision}", flush=True)
    print(f"CLONE_BLIND_A_SCORE_REPORT={score_path}", flush=True)
    print(f"CLONE_BLIND_A_SCORE_REPORT_SHA256={_sha256(score_path)}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sealed AISHELL-3 Base-vs-CustomVoice clone blind-test runner."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="verify official data, convert references, and freeze the run"
    )
    prepare.add_argument("--dataset-root", type=Path, required=True)
    prepare.add_argument("--archive", type=Path, required=True)
    prepare.add_argument(
        "--speaker-id",
        action="append",
        required=True,
        help="repeat exactly eight times; selection must be 4M/4F with matched age/accent marginals",
    )
    prepare.add_argument("--catch-speaker-id")
    prepare.add_argument(
        "--selection-note",
        default="explicit CLI speaker IDs frozen before generation",
    )
    prepare.add_argument("--run-id")
    prepare.add_argument("--probe-root", type=Path, default=DEFAULT_PROBE_ROOT)
    prepare.add_argument("--base-model-dir", type=Path, default=DEFAULT_BASE_MODEL_DIR)
    prepare.add_argument(
        "--custom-model-dir", type=Path, default=DEFAULT_CUSTOM_MODEL_DIR
    )
    prepare.add_argument("--onnx-provider", default="DML")
    prepare.add_argument(
        "--llm-use-gpu",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    prepare.set_defaults(func=_prepare)

    generate = subparsers.add_parser(
        "generate", help="verify the frozen run and generate both arms"
    )
    generate.add_argument("--run-id", required=True)
    generate.set_defaults(func=_generate)

    score = subparsers.add_parser(
        "score", help="validate completed ratings, reveal once, and apply the fixed rule"
    )
    score.add_argument("--run-id", required=True)
    score.add_argument("--ratings", type=Path)
    score.set_defaults(func=_score)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare" and len(args.speaker_id) != 8:
        raise RuntimeError(
            f"--speaker-id must be repeated exactly eight times, got {len(args.speaker_id)}"
        )
    args.func(args)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
