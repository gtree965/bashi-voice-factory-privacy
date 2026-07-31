import hashlib
import tempfile
import unittest
from pathlib import Path


class DownloadUtilsTests(unittest.TestCase):
    def test_sha256_file_hashes_across_multiple_chunks(self):
        from download_utils import SHA256_CHUNK_SIZE, sha256_file

        payload = (b"bashi-download-utils\0" * ((SHA256_CHUNK_SIZE // 21) + 2))
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "payload.bin"
            path.write_bytes(payload)

            self.assertEqual(sha256_file(path), hashlib.sha256(payload).hexdigest())

    def test_three_download_modules_share_one_sha256_implementation(self):
        import download_cuda_runtime
        import download_gguf_model
        import download_utils
        import model_manager

        self.assertIs(download_cuda_runtime.sha256_file, download_utils.sha256_file)
        self.assertIs(download_gguf_model.sha256_file, download_utils.sha256_file)
        self.assertIs(model_manager.sha256_file, download_utils.sha256_file)


if __name__ == "__main__":
    unittest.main()
