"""Download and verify the Bashi GGUF runtime model pack.

Primary source: ModelScope repository containing model-custom/manifest.json.
Fallback source: a manually supplied zip URL, for example Files.fm.

This script is intentionally dependency-free so it can run inside the portable
package before optional helper packages are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET_DIR = (APP_ROOT.parent / "vulkan_backend_spike" / "Qwen3-TTS-GGUF" / "model-custom").resolve()
DEFAULT_MODELSCOPE_REPO = os.environ.get(
    "BASHI_GGUF_MODELSCOPE_REPO",
    "gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime",
)
DEFAULT_FILESFM_URL = os.environ.get("BASHI_GGUF_FILESFM_URL", "")
DEFAULT_FILESFM_SHA256 = os.environ.get("BASHI_GGUF_FILESFM_SHA256", "")
CHUNK_SIZE = 1024 * 1024
REQUIRED_RUNTIME_PATHS = (
    "qwen3_tts_talker.q5_k.gguf",
    "qwen3_tts_predictor.q8_0.gguf",
    "qwen3_tts_decoder.fp16.onnx",
    "tokenizer.json",
    "embeddings/text_embedding_projected.npy",
    "embeddings/proj_weight.npy",
    "embeddings/proj_bias.npy",
)
OPTIONAL_MANIFEST_PATHS = {"README_RUNTIME_PACK.md"}


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.replace("\\", "/").split("/"))


def modelscope_resolve_url(repo_id: str, path: str, revision: str = "master") -> str:
    encoded_repo = "/".join(urllib.parse.quote(part) for part in repo_id.strip("/").split("/"))
    encoded_path = quote_path(path)
    return f"https://modelscope.cn/models/{encoded_repo}/resolve/{revision}/{encoded_path}"


def request_url(url: str, start: int = 0) -> urllib.request.Request:
    headers = {"User-Agent": "BashiVoiceFactory/4.0"}
    if start > 0:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.Request(url, headers=headers)


def download_file(url: str, dest: Path, expected_sha256: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    resume_at = part.stat().st_size if part.exists() else 0
    mode = "ab" if resume_at else "wb"

    try:
        with urllib.request.urlopen(request_url(url, resume_at), timeout=600) as response:
            if resume_at and getattr(response, "status", None) != 206:
                print(f"  {dest.name}: server did not accept resume; restarting this file")
                resume_at = 0
                mode = "wb"
            total = response.headers.get("Content-Length")
            total_bytes = int(total) + resume_at if total and total.isdigit() else None
            downloaded = resume_at
            with part.open(mode) as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes:
                        pct = downloaded / total_bytes * 100
                        print(f"  {dest.name}: {pct:5.1f}% ({downloaded / 1024 / 1024:.1f} MiB)", end="\r")
            print()
    except Exception as exc:
        raise DownloadError(f"download failed for {url}: {exc}") from exc

    if expected_sha256:
        actual = sha256_file(part)
        if actual.lower() != expected_sha256.lower():
            part.unlink(missing_ok=True)
            raise DownloadError(
                f"checksum mismatch for {dest.name}: expected {expected_sha256[:12]}..., got {actual[:12]}..."
            )

    part.replace(dest)


def load_local_manifest(target_dir: Path) -> dict | None:
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def verify_manifest(target_dir: Path, manifest: dict, quiet: bool = False) -> bool:
    ok = True
    for item in manifest.get("files", []):
        rel = item["path"]
        if rel in OPTIONAL_MANIFEST_PATHS:
            continue
        expected = item.get("sha256")
        path = target_dir / rel
        if not path.exists():
            if not quiet:
                print(f"missing: {rel}")
            ok = False
            continue
        if expected:
            actual = sha256_file(path)
            if actual.lower() != expected.lower():
                if not quiet:
                    print(f"bad sha256: {rel}")
                ok = False
    return ok


def has_required_runtime_files(target_dir: Path) -> bool:
    return all((target_dir / rel).exists() for rel in REQUIRED_RUNTIME_PATHS)


def download_from_modelscope(repo_id: str, target_dir: Path, revision: str) -> None:
    if not repo_id:
        raise DownloadError("ModelScope repo id is required. Use --modelscope-repo or BASHI_GGUF_MODELSCOPE_REPO.")

    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_url = modelscope_resolve_url(repo_id, "model-custom/manifest.json", revision)
    manifest_path = target_dir / "manifest.json"

    print(f"Downloading manifest from ModelScope: {repo_id}")
    download_file(manifest_url, manifest_path)
    manifest = load_local_manifest(target_dir)
    if not manifest:
        raise DownloadError("Downloaded manifest.json could not be read.")

    for index, item in enumerate(manifest.get("files", []), start=1):
        rel = item["path"]
        dest = target_dir / rel
        expected = item.get("sha256")
        expected_for_download = None if rel in OPTIONAL_MANIFEST_PATHS else expected
        if dest.exists() and expected and sha256_file(dest).lower() == expected.lower():
            print(f"[{index}] ok: {rel}")
            continue
        if dest.exists() and rel in OPTIONAL_MANIFEST_PATHS:
            print(f"[{index}] ok: {rel} (optional doc)")
            continue
        url = modelscope_resolve_url(repo_id, f"model-custom/{rel}", revision)
        print(f"[{index}] downloading: {rel}")
        if rel in OPTIONAL_MANIFEST_PATHS:
            try:
                download_file(url, dest, expected_for_download)
            except DownloadError as exc:
                print(f"[{index}] optional doc skipped: {rel} ({exc})")
            continue
        download_file(url, dest, expected_for_download)

    if not verify_manifest(target_dir, manifest):
        raise DownloadError("ModelScope download finished but manifest verification failed.")


def print_modelscope_recovery_hint(error: Exception) -> None:
    print(f"ModelScope download failed: {error}")
    print()
    print("ModelScope may be temporarily unavailable, rate-limited, or interrupted by the network.")
    print("ModelScope 可能暂时不可用、触发限流，或被当前网络中断。")
    print()
    print("You can retry later, or provide a fallback zip URL with:")
    print("稍后可重试，或用备用 zip 链接下载：")
    print()
    print("  $env:BASHI_GGUF_FILESFM_URL = \"https://.../gguf-runtime.zip\"")
    print("  .\\.venv\\Scripts\\python.exe download_gguf_model.py")
    print()
    print("If the fallback zip has a known SHA256, also set:")
    print("如果备用 zip 有 SHA256，也可以设置：")
    print()
    print("  $env:BASHI_GGUF_FILESFM_SHA256 = \"<sha256>\"")


def download_zip_fallback(url: str, target_dir: Path, zip_sha256: str | None = None) -> None:
    if not url:
        raise DownloadError("fallback zip URL is empty")

    with tempfile.TemporaryDirectory(prefix="bashi-gguf-download-") as tmpdir:
        tmp = Path(tmpdir)
        zip_path = tmp / "gguf-runtime.zip"
        print("Downloading fallback zip...")
        download_file(url, zip_path, zip_sha256 or None)

        extract_dir = tmp / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        model_dir = extract_dir / "model-custom"
        if not model_dir.exists():
            nested = list(extract_dir.glob("*/model-custom"))
            if nested:
                model_dir = nested[0]
        if not model_dir.exists():
            raise DownloadError("fallback zip does not contain model-custom/")

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(model_dir, target_dir)

    manifest = load_local_manifest(target_dir)
    if not manifest:
        raise DownloadError("fallback zip did not include model-custom/manifest.json")
    if not verify_manifest(target_dir, manifest):
        raise DownloadError("fallback zip extraction failed manifest verification")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Bashi GGUF runtime model pack.")
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR), help="Destination model-custom directory.")
    parser.add_argument("--modelscope-repo", default=DEFAULT_MODELSCOPE_REPO, help="ModelScope repo id, e.g. namespace/repo.")
    parser.add_argument("--revision", default="master", help="ModelScope revision/branch.")
    parser.add_argument("--filesfm-url", default=DEFAULT_FILESFM_URL, help="Optional fallback zip URL.")
    parser.add_argument("--filesfm-sha256", default=DEFAULT_FILESFM_SHA256, help="Optional fallback zip SHA256.")
    parser.add_argument("--check-only", action="store_true", help="Only verify an already installed model-custom directory.")
    parser.add_argument("--fallback-only", action="store_true", help="Skip ModelScope and use the fallback zip URL.")
    args = parser.parse_args()

    target_dir = Path(args.target_dir).resolve()

    if args.check_only:
        manifest = load_local_manifest(target_dir)
        if manifest and verify_manifest(target_dir, manifest):
            print(f"GGUF runtime pack is complete: {target_dir}")
            return 0
        if not manifest and has_required_runtime_files(target_dir):
            print(f"GGUF runtime pack appears complete without manifest: {target_dir}")
            print("Run without --check-only to download manifest.json and verify SHA256 checksums.")
            return 0
        print(f"GGUF runtime pack is missing or incomplete: {target_dir}")
        return 1

    try:
        if args.fallback_only:
            download_zip_fallback(args.filesfm_url, target_dir, args.filesfm_sha256)
        else:
            try:
                download_from_modelscope(args.modelscope_repo, target_dir, args.revision)
            except Exception as exc:
                if not args.filesfm_url:
                    print_modelscope_recovery_hint(exc)
                    return 1
                print_modelscope_recovery_hint(exc)
                print("Trying fallback zip...")
                download_zip_fallback(args.filesfm_url, target_dir, args.filesfm_sha256)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"GGUF runtime pack is ready: {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
