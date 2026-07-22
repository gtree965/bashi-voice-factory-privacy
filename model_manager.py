import os
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Generator, Optional

from download_utils import sha256_file


IDLE_TIMEOUT_SECONDS = 30.0
PROGRESS_INTERVAL_SECONDS = 0.5
DOWNLOAD_CHUNK_SIZE = 64 * 1024


# Model registry
MODEL_REGISTRY = {
    "sensevoice-small-int8": {
        "name": "SenseVoice Small (INT8)",
        "name_zh": "SenseVoice 小型 (INT8量化)",
        "engine": "sherpa-onnx",
        "size_mb": 242,
        "languages": ["zh", "en", "ja", "ko", "yue"],
        "files": {
            "model.int8.onnx": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx",
                "sha256": "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
            },
            "tokens.txt": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt",
                "sha256": "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
            },
        },
        "is_default": True,
        "description": "Default fast multilingual ASR for Chinese/English/Cantonese. ~242MB download.",
        "description_zh": "默认快速多语种识别档，支持中英粤语，约242MB。",
    },
    "parakeet-tdt-0.6b-v2-int8": {
        "name": "Parakeet TDT 0.6B (INT8)",
        "name_zh": "Parakeet TDT 0.6B (INT8量化)",
        "engine": "sherpa-onnx",
        "size_mb": 661,
        "languages": ["en"],
        "files": {
            "encoder.int8.onnx": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/encoder.int8.onnx",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/encoder.int8.onnx",
                "sha256": "a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab",
            },
            "decoder.int8.onnx": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/decoder.int8.onnx",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/decoder.int8.onnx",
                "sha256": "b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e",
            },
            "joiner.int8.onnx": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/joiner.int8.onnx",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/joiner.int8.onnx",
                "sha256": "7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2",
            },
            "tokens.txt": {
                "url": "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/tokens.txt",
                "mirror": "https://hf-mirror.com/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main/tokens.txt",
                "sha256": "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d",
            },
        },
        "is_default": False,
        "description": "Best English ASR. NVIDIA Parakeet, ~1.7% WER. ~661MB download.",
        "description_zh": "最佳英文语音识别，NVIDIA Parakeet，约661MB。",
    },
}

# VAD model (shared across engines)
VAD_MODEL = {
    "silero_vad.onnx": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "size_mb": 2,
        "sha256": "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
    }
}

SPEAKER_DIARIZATION_MODEL = {
    "id": "speaker-diarization-pyannote-3dspeaker",
    "name": "Speaker ID (pyannote + 3D-Speaker)",
    "name_zh": "说话人识别 (pyannote + 3D-Speaker)",
    "size_mb": 73,
    "description": "Offline speaker labels for meetings. Adds Speaker 1/2/3... to transcript exports.",
    "description_zh": "本地多人说话人标注，为会议转写添加“说话人 1/2/3...”前缀。",
    "required_files": [
        "speaker-diarization/sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx",
        "speaker-diarization/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        "speaker-diarization/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
    ],
    "files": {
        "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2": {
            "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
            "sha256": "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
            "extract": True,
            "complete_path": "speaker-diarization/sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx",
        },
        "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx": {
            "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
            "sha256": "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
            "complete_path": "speaker-diarization/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        },
        "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx": {
            "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
            "sha256": "f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11",
            "complete_path": "speaker-diarization/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
        },
    },
}


def _build_url_order(file_meta: dict, use_mirror: bool = True) -> list:
    urls = []
    if use_mirror and file_meta.get("mirror"):
        urls.append(file_meta["mirror"])
    if file_meta.get("url"):
        urls.append(file_meta["url"])
    if not use_mirror and file_meta.get("mirror"):
        urls.append(file_meta["mirror"])
    seen = set()
    deduped = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


class ModelManager:
    """Manage ASR model downloads and availability."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def list_installed(self) -> list:
        installed = []
        for model_id, meta in MODEL_REGISTRY.items():
            if self._is_model_complete(model_id):
                installed.append({**meta, "id": model_id})
        return installed

    def list_available(self) -> list:
        available = []
        for model_id, meta in MODEL_REGISTRY.items():
            if not self._is_model_complete(model_id):
                available.append({**meta, "id": model_id})
        return available

    def get_speaker_diarization_status(self) -> dict:
        meta = {
            k: v for k, v in SPEAKER_DIARIZATION_MODEL.items()
            if k not in ("files", "required_files")
        }
        return {
            **meta,
            "installed": self.is_speaker_diarization_complete(),
            "ui_enabled": os.environ.get("BASHI_SPEAKER_ID_UI") == "1",
        }

    def is_speaker_diarization_complete(self) -> bool:
        return all(
            self._path_exists(self.models_dir / rel_path)
            for rel_path in SPEAKER_DIARIZATION_MODEL["required_files"]
        )

    def _is_model_complete(self, model_id: str) -> bool:
        meta = MODEL_REGISTRY.get(model_id)
        if not meta:
            return False
        model_dir = self.models_dir / model_id
        return all(
            (model_dir / fname).exists()
            for fname in meta["files"]
        )

    def get_model_dir(self, model_id: str) -> Optional[Path]:
        if self._is_model_complete(model_id):
            return self.models_dir / model_id
        return None

    def get_default_model_dir(self) -> Optional[Path]:
        for model_id, meta in MODEL_REGISTRY.items():
            if meta.get("is_default") and self._is_model_complete(model_id):
                return self.models_dir / model_id
        for model_id in MODEL_REGISTRY:
            if self._is_model_complete(model_id):
                return self.models_dir / model_id
        return None

    def get_speaker_diarization_dir(self) -> Optional[Path]:
        if self.is_speaker_diarization_complete():
            return self.models_dir / "speaker-diarization"
        return None

    def download_model(
        self,
        model_id: str,
        use_mirror: bool = True
    ) -> Generator[dict, None, None]:
        """Download model files with byte-level progress updates."""
        meta = MODEL_REGISTRY.get(model_id)
        if not meta:
            yield {"status": "error", "error": f"Unknown model: {model_id}"}
            return

        model_dir = self.models_dir / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        # VAD is a shared prerequisite; count it toward the total only if it
        # actually needs to be downloaded, so the progress denominator stays
        # honest across repeat downloads of different models.
        vad_path = self.models_dir / "silero_vad.onnx"
        need_vad = not vad_path.exists()
        total_files = len(meta["files"]) + (1 if need_vad else 0)
        files_done = 0

        if need_vad:
            vad_meta = VAD_MODEL["silero_vad.onnx"]
            url_order = _build_url_order(vad_meta, use_mirror=use_mirror)
            yield from self._download_one_file(
                fname="silero_vad.onnx",
                file_meta=vad_meta,
                dest=vad_path,
                url_order=url_order,
                files_done=files_done,
                total_files=total_files,
            )
            files_done += 1

        for fname, file_meta in meta["files"].items():
            dest = model_dir / fname
            if dest.exists():
                files_done += 1
                continue

            url_order = _build_url_order(file_meta, use_mirror=use_mirror)
            if not url_order:
                yield {"status": "error", "error": f"No download URLs configured for {fname}"}
                return

            try:
                yield from self._download_one_file(
                    fname=fname,
                    file_meta=file_meta,
                    dest=dest,
                    url_order=url_order,
                    files_done=files_done,
                    total_files=total_files,
                )
            except RuntimeError as e:
                yield {"status": "error", "error": str(e)}
                return
            files_done += 1

        yield {"status": "done", "model_id": model_id}

    def download_speaker_diarization_model(
        self,
        use_mirror: bool = True
    ) -> Generator[dict, None, None]:
        """Download the optional local Speaker ID model pack."""
        model_root = self.models_dir / "speaker-diarization"
        model_root.mkdir(parents=True, exist_ok=True)

        pending = []
        for fname, file_meta in SPEAKER_DIARIZATION_MODEL["files"].items():
            complete_path = self.models_dir / file_meta["complete_path"]
            if not self._path_exists(complete_path):
                pending.append((fname, file_meta))

        if not pending:
            yield {
                "status": "done",
                "model_id": SPEAKER_DIARIZATION_MODEL["id"],
            }
            return

        total_files = len(pending)
        files_done = 0
        for fname, file_meta in pending:
            dest = model_root / fname
            url_order = _build_url_order(file_meta, use_mirror=use_mirror)
            if not url_order:
                yield {"status": "error", "error": f"No download URLs configured for {fname}"}
                return

            try:
                yield from self._download_one_file(
                    fname=fname,
                    file_meta=file_meta,
                    dest=dest,
                    url_order=url_order,
                    files_done=files_done,
                    total_files=total_files,
                )
                if file_meta.get("extract"):
                    yield {
                        "status": "downloading",
                        "file": fname,
                        "file_index": files_done + 1,
                        "total_files": total_files,
                        "progress": round(((files_done + 1) / total_files) * 100, 1),
                        "message": f"Extracting {fname}...",
                        "message_zh": f"正在解压 {fname}...",
                    }
                    self._extract_tar_safely(dest, model_root)
                    dest.unlink(missing_ok=True)
            except Exception as e:
                yield {"status": "error", "error": str(e)}
                return
            files_done += 1

        yield {
            "status": "done",
            "model_id": SPEAKER_DIARIZATION_MODEL["id"],
        }

    def _download_one_file(
        self,
        fname: str,
        file_meta: dict,
        dest: Path,
        url_order: list,
        files_done: int,
        total_files: int,
    ) -> Generator[dict, None, None]:
        """Try url_order in sequence; yield events; raise RuntimeError if all mirrors fail."""
        # Initial "starting" event so the UI flips to this file immediately,
        # even before the first chunk arrives.
        yield {
            "status": "downloading",
            "file": fname,
            "file_index": files_done + 1,
            "total_files": total_files,
            "bytes_done": 0,
            "bytes_total": None,
            "progress": round((files_done / total_files) * 100, 1) if total_files else 0,
            "message": f"Starting {fname}...",
            "message_zh": f"开始下载 {fname}...",
        }

        last_error = None
        for url_idx, url in enumerate(url_order):
            try:
                yield from self._download_file_streaming(
                    url=url,
                    dest=dest,
                    expected_sha256=file_meta.get("sha256"),
                    fname_for_progress=fname,
                    files_done=files_done,
                    total_files=total_files,
                )
                return
            except Exception as e:
                last_error = e
                if url_idx < len(url_order) - 1:
                    yield {
                        "status": "downloading",
                        "file": fname,
                        "file_index": files_done + 1,
                        "total_files": total_files,
                        "message": f"Mirror failed ({type(e).__name__}), trying fallback for {fname}...",
                        "message_zh": f"镜像失败 ({type(e).__name__})，正在尝试备用源 {fname}...",
                    }

        raise RuntimeError(f"Download failed for {fname}: {last_error}")

    def _download_file_streaming(
        self,
        url: str,
        dest: Path,
        expected_sha256: Optional[str],
        fname_for_progress: str,
        files_done: int,
        total_files: int,
    ) -> Generator[dict, None, None]:
        """Stream a file to disk with HTTP Range/resume + byte progress yields.

        Preserves the .part file across transient failures so the next mirror
        attempt (or the next user retry) can resume from where this one stopped.
        Only deletes .part on a hard checksum mismatch (bad body).
        """
        part = dest.with_suffix(dest.suffix + ".part")
        resume_at = part.stat().st_size if part.exists() else 0
        mode = "ab" if resume_at else "wb"

        headers = {"User-Agent": "BashiVoiceFactory/0.1"}
        if resume_at:
            headers["Range"] = f"bytes={resume_at}-"
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=IDLE_TIMEOUT_SECONDS) as response:
            if resume_at and getattr(response, "status", None) != 206:
                # Server ignored Range; restart this file from 0
                resume_at = 0
                mode = "wb"

            total_header = response.headers.get("Content-Length")
            body_remaining = int(total_header) if total_header and total_header.isdigit() else None
            total_bytes = (body_remaining + resume_at) if body_remaining is not None else None

            downloaded = resume_at
            last_report = 0.0

            with open(part, mode) as out_file:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= PROGRESS_INTERVAL_SECONDS:
                        yield self._progress_event(
                            fname_for_progress, files_done, total_files,
                            downloaded, total_bytes,
                        )
                        last_report = now

            yield self._progress_event(
                fname_for_progress, files_done, total_files,
                downloaded, total_bytes,
            )

        if expected_sha256:
            actual = sha256_file(part)
            if actual.lower() != expected_sha256.lower():
                part.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Checksum mismatch for {dest.name}: "
                    f"expected {expected_sha256[:12]}..., got {actual[:12]}..."
                )

        part.replace(dest)

    @staticmethod
    def _extract_tar_safely(archive_path: Path, dest_dir: Path) -> None:
        dest_root = dest_dir.resolve()
        with tarfile.open(archive_path, "r:bz2") as tar:
            members = tar.getmembers()
            for member in members:
                if member.issym() or member.islnk():
                    raise RuntimeError(f"Refusing to extract link from model archive: {member.name}")
                target = (dest_root / member.name).resolve()
                target_text = str(target)
                root_text = str(dest_root)
                if target_text != root_text and not target_text.startswith(root_text + os.sep):
                    raise RuntimeError(f"Refusing to extract unsafe path: {member.name}")
            tar.extractall(dest_root, members=members)

    @staticmethod
    def _path_exists(path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return False

    @staticmethod
    def _progress_event(
        fname: str,
        files_done: int,
        total_files: int,
        bytes_done: int,
        bytes_total: Optional[int],
    ) -> dict:
        within_file = (bytes_done / bytes_total) if bytes_total else 0
        overall = ((files_done + within_file) / total_files) * 100 if total_files else 0
        mb_done = bytes_done / 1024 / 1024
        mb_total_text = f" / {bytes_total / 1024 / 1024:.1f} MB" if bytes_total else ""
        return {
            "status": "downloading",
            "file": fname,
            "file_index": files_done + 1,
            "total_files": total_files,
            "bytes_done": bytes_done,
            "bytes_total": bytes_total,
            "progress": round(overall, 1),
            "message": f"Downloading {fname}... {mb_done:.1f} MB{mb_total_text}",
            "message_zh": f"正在下载 {fname}... {mb_done:.1f} MB{mb_total_text}",
        }
