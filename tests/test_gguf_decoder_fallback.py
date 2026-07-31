import sys
import unittest
import multiprocessing.spawn as mp_spawn
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import local_tts_engine_gguf as gguf
from audio_encoding import peak_normalize_audio


class _Stream:
    def __init__(self, audio):
        self.result = SimpleNamespace(audio=audio)
        self.shutdown = Mock()

    def custom(self, **_kwargs):
        return self.result


class _Engine:
    ready = True

    def __init__(self, audio):
        self.stream = _Stream(audio)
        self.shutdown = Mock()

    def create_stream(self):
        return self.stream


class GgufDecoderFallbackTests(unittest.TestCase):
    def test_spawn_command_line_forces_utf8_mode_idempotently(self) -> None:
        patched = mp_spawn.get_command_line

        command = patched(pipe_handle=123)
        gguf._install_worker_utf8_spawn_patch()
        repeated_command = mp_spawn.get_command_line(pipe_handle=123)

        self.assertIs(patched, mp_spawn.get_command_line)
        self.assertTrue(getattr(mp_spawn.get_command_line, "_bashi_utf8", False))
        self.assertIn("-X", command)
        self.assertIn("utf8=1", command)
        self.assertEqual(1, command.count("utf8=1"))
        self.assertEqual(1, repeated_command.count("utf8=1"))

    def test_ensure_loaded_uses_instance_provider_override(self) -> None:
        service = gguf.LocalTTSService()
        service._onnx_provider_override = "CPU"
        inference_module = ModuleType("qwen3_tts_gguf.inference")
        engine = _Engine(np.array([0.1], dtype=np.float32))
        inference_module.TTSEngine = Mock(return_value=engine)

        with patch.dict(sys.modules, {"qwen3_tts_gguf.inference": inference_module}):
            with patch("local_tts_engine_gguf._patch_decoder_ready_timeout"):
                self.assertIs(engine, service._ensure_loaded())

        self.assertEqual(
            "CPU",
            inference_module.TTSEngine.call_args.kwargs["onnx_provider"],
        )

    def test_available_dml_provider_is_passed_through(self) -> None:
        service = gguf.LocalTTSService()
        inference_module = ModuleType("qwen3_tts_gguf.inference")
        engine = _Engine(np.array([0.1], dtype=np.float32))
        inference_module.TTSEngine = Mock(return_value=engine)
        ort_module = ModuleType("onnxruntime")
        ort_module.get_available_providers = Mock(
            return_value=["DmlExecutionProvider", "CPUExecutionProvider"]
        )

        with patch.dict(
            sys.modules,
            {
                "onnxruntime": ort_module,
                "qwen3_tts_gguf.inference": inference_module,
            },
        ):
            with patch("local_tts_engine_gguf._patch_decoder_ready_timeout"):
                service._ensure_loaded()

        self.assertEqual(
            "DML",
            inference_module.TTSEngine.call_args.kwargs["onnx_provider"],
        )
        self.assertIsNone(service._onnx_provider_override)

    def test_unavailable_dml_provider_falls_back_before_engine_start(self) -> None:
        service = gguf.LocalTTSService()
        inference_module = ModuleType("qwen3_tts_gguf.inference")
        engine = _Engine(np.array([0.1], dtype=np.float32))
        inference_module.TTSEngine = Mock(return_value=engine)
        ort_module = ModuleType("onnxruntime")
        ort_module.get_available_providers = Mock(return_value=["CPUExecutionProvider"])

        with patch.dict(
            sys.modules,
            {
                "onnxruntime": ort_module,
                "qwen3_tts_gguf.inference": inference_module,
            },
        ):
            with patch("local_tts_engine_gguf._patch_decoder_ready_timeout"):
                with patch.object(gguf.logger, "warning") as log:
                    service._ensure_loaded()

        self.assertEqual(
            "CPU",
            inference_module.TTSEngine.call_args.kwargs["onnx_provider"],
        )
        self.assertEqual("CPU", service._onnx_provider_override)
        self.assertIn("falling back to CPU decoder", log.call_args.args[0])

    def test_broken_onnxruntime_fails_before_engine_start(self) -> None:
        service = gguf.LocalTTSService()

        with patch.dict(sys.modules, {"onnxruntime": None}):
            with self.assertRaisesRegex(gguf.LocalTTSError, "onnxruntime 安装损坏"):
                service._ensure_loaded()

    def test_closing_sentence_stream_cancels_and_allows_immediate_restart(self) -> None:
        service = gguf.LocalTTSService()
        cancel_events = []
        iter_from_queue = service._iter_from_queue

        def capture_cancel_event(event_queue, cancel_event):
            cancel_events.append(cancel_event)
            return iter_from_queue(event_queue, cancel_event)

        with patch.object(
            service,
            "_normalize_and_split_chunks",
            side_effect=lambda chunks: chunks,
        ), patch.object(
            service,
            "_generate_mp3_no_lock",
            return_value="fake.mp3",
        ), patch.object(
            service,
            "_iter_from_queue",
            side_effect=capture_cancel_event,
        ):
            stream = service.synthesize_sentences_stream(
                ["First chunk.", "Second chunk."],
                "uncle_fu",
            )
            self.assertEqual("generating", next(stream)["status"])
            self.assertEqual("sentence_done", next(stream)["status"])
            stream.close()

            self.assertTrue(cancel_events[0].is_set())
            restarted = service.synthesize_sentences_stream(
                ["Restarted chunk."],
                "uncle_fu",
            )
            self.assertEqual("generating", next(restarted)["status"])
            restarted.close()

    def test_long_stream_emits_preview_for_each_group_and_trimmed_duration(self) -> None:
        service = gguf.LocalTTSService()
        first_audio = np.arange(12, dtype=np.float32)
        second_audio = np.arange(8, dtype=np.float32)

        with patch.object(
            service,
            "_split_long_text",
            return_value=["First group.", "Second group."],
        ), patch.object(
            service,
            "_coalesce_long_chunks",
            side_effect=lambda chunks: chunks,
        ), patch.object(
            service,
            "_generate_wav_no_lock",
            side_effect=[(first_audio, 4), (second_audio, 4)],
        ), patch.object(
            service,
            "_trim_long_chunk_audio",
            side_effect=[first_audio[:8], second_audio[:4]],
        ), patch.object(
            service,
            "_long_join_gap",
            return_value=np.array([], dtype=np.float32),
        ), patch(
            "local_tts_engine_gguf.write_mp3",
            side_effect=["preview-1.mp3", "preview-2.mp3", "final.mp3"],
        ) as write_mp3:
            events = list(service.synthesize_long_stream("Long text", "uncle_fu"))

        self.assertEqual(
            ["generating", "chunk_done", "generating", "chunk_done", "merging", "done"],
            [event["status"] for event in events],
        )
        previews = [event for event in events if event["status"] == "chunk_done"]
        self.assertEqual(["/static/audio/preview-1.mp3", "/static/audio/preview-2.mp3"], [
            event["audio_url"] for event in previews
        ])
        self.assertEqual([2.0, 1.0], [event["duration"] for event in previews])
        self.assertEqual("/static/audio/final.mp3", events[-1]["audio_url_mp3"])
        self.assertFalse(write_mp3.call_args_list[0].kwargs["normalize_peak"])
        self.assertFalse(write_mp3.call_args_list[1].kwargs["normalize_peak"])
        self.assertNotIn("normalize_peak", write_mp3.call_args_list[2].kwargs)

    def test_long_group_count_matches_stream_total_for_the_same_text(self) -> None:
        service = gguf.LocalTTSService()
        text = (
            "太初之时，天地浑然未分。清气上升，浊气下沉；于是上下始判，乾坤乃定。"
            "山岳隆起，江河顺势而流。草木萌发于野，鸟兽栖息于林。"
        )
        audio = np.ones(8, dtype=np.float32)
        group_count = service.count_long_groups(text)

        with patch.object(
            service,
            "_generate_wav_no_lock",
            return_value=(audio, 4),
        ), patch.object(
            service,
            "_trim_long_chunk_audio",
            return_value=audio,
        ), patch.object(
            service,
            "_long_join_gap",
            return_value=np.array([], dtype=np.float32),
        ), patch(
            "local_tts_engine_gguf.write_mp3",
            return_value="fake.mp3",
        ):
            events = list(service.synthesize_long_stream(text, "uncle_fu"))

        stream_totals = {
            event["total"]
            for event in events
            if event["status"] == "generating"
        }
        self.assertGreater(group_count, 0)
        self.assertEqual({group_count}, stream_totals)

    def test_long_preview_encoding_failure_does_not_block_final_audio(self) -> None:
        service = gguf.LocalTTSService()
        audio = np.arange(8, dtype=np.float32)

        with patch.object(
            service,
            "_split_long_text",
            return_value=["Only group."],
        ), patch.object(
            service,
            "_coalesce_long_chunks",
            side_effect=lambda chunks: chunks,
        ), patch.object(
            service,
            "_generate_wav_no_lock",
            return_value=(audio, 4),
        ), patch.object(
            service,
            "_trim_long_chunk_audio",
            return_value=audio,
        ), patch(
            "local_tts_engine_gguf.write_mp3",
            side_effect=[RuntimeError("preview failed"), "final.mp3"],
        ), patch.object(gguf.logger, "warning") as warning:
            events = list(service.synthesize_long_stream("Long text", "uncle_fu"))

        self.assertNotIn("chunk_done", [event["status"] for event in events])
        self.assertEqual("done", events[-1]["status"])
        self.assertEqual("/static/audio/final.mp3", events[-1]["audio_url_mp3"])
        warning.assert_called_once()

    def test_long_stream_skipped_group_has_no_preview_event(self) -> None:
        service = gguf.LocalTTSService()
        audio = np.arange(8, dtype=np.float32)

        with patch.object(
            service,
            "_split_long_text",
            return_value=["【 古书1:1-8】", "Spoken group."],
        ), patch.object(
            service,
            "_coalesce_long_chunks",
            side_effect=lambda chunks: chunks,
        ), patch.object(
            service,
            "_generate_wav_no_lock",
            return_value=(audio, 4),
        ), patch.object(
            service,
            "_trim_long_chunk_audio",
            return_value=audio,
        ), patch(
            "local_tts_engine_gguf.write_mp3",
            side_effect=["preview.mp3", "final.mp3"],
        ):
            events = list(service.synthesize_long_stream("Long text", "uncle_fu"))

        generating = [event for event in events if event["status"] == "generating"]
        previews = [event for event in events if event["status"] == "chunk_done"]
        self.assertEqual([1, 2], [event["chunk"] for event in generating])
        self.assertEqual([2], [event["chunk"] for event in previews])

    def test_closing_long_stream_cancels_and_allows_immediate_restart(self) -> None:
        service = gguf.LocalTTSService()
        cancel_events = []
        iter_from_queue = service._iter_from_queue
        audio = np.arange(8, dtype=np.float32)

        def capture_cancel_event(event_queue, cancel_event):
            cancel_events.append(cancel_event)
            return iter_from_queue(event_queue, cancel_event)

        with patch.object(
            service,
            "_split_long_text",
            return_value=["First group.", "Second group."],
        ), patch.object(
            service,
            "_coalesce_long_chunks",
            side_effect=lambda chunks: chunks,
        ), patch.object(
            service,
            "_generate_wav_no_lock",
            return_value=(audio, 4),
        ), patch.object(
            service,
            "_trim_long_chunk_audio",
            return_value=audio,
        ), patch.object(
            service,
            "_long_join_gap",
            return_value=np.array([], dtype=np.float32),
        ), patch.object(
            service,
            "_iter_from_queue",
            side_effect=capture_cancel_event,
        ), patch(
            "local_tts_engine_gguf.write_mp3",
            return_value="fake.mp3",
        ):
            stream = service.synthesize_long_stream("Long text", "uncle_fu")
            self.assertEqual("generating", next(stream)["status"])
            self.assertEqual("chunk_done", next(stream)["status"])
            stream.close()

            self.assertTrue(cancel_events[0].is_set())
            restarted = service.synthesize_long_stream("Restarted text", "uncle_fu")
            self.assertEqual("generating", next(restarted)["status"])
            restarted.close()

    def test_empty_dml_audio_rebuilds_on_cpu_and_retries_once(self) -> None:
        service = gguf.LocalTTSService()
        dml_engine = _Engine(np.array([], dtype=np.float32))
        cpu_engine = _Engine(np.array([0.2, -0.4], dtype=np.float32))
        service._engine = dml_engine
        service._state = "ready"

        with patch.object(
            service,
            "_ensure_loaded",
            side_effect=[dml_engine, cpu_engine],
        ) as ensure_loaded:
            with patch.object(service, "_build_config", return_value=object()):
                with patch.object(gguf.logger, "warning") as log:
                    audio, sample_rate = service._generate_wav_no_lock(
                        "测试",
                        "uncle_fu",
                    )

        self.assertEqual(2, ensure_loaded.call_count)
        self.assertEqual("CPU", service._onnx_provider_override)
        self.assertEqual(gguf.SAMPLE_RATE, sample_rate)
        np.testing.assert_allclose(
            peak_normalize_audio(np.array([0.2, -0.4], dtype=np.float32)),
            audio,
        )
        dml_engine.shutdown.assert_called_once_with()
        dml_engine.stream.shutdown.assert_called_once_with()
        cpu_engine.stream.shutdown.assert_called_once_with()
        self.assertIn("falling back to CPU decoder", log.call_args.args[0])

    def test_empty_cpu_audio_raises_without_retry(self) -> None:
        service = gguf.LocalTTSService()
        service._onnx_provider_override = "CPU"
        cpu_engine = _Engine(np.array([], dtype=np.float32))
        service._engine = cpu_engine
        service._state = "ready"

        with patch.object(service, "_ensure_loaded", return_value=cpu_engine) as ensure_loaded:
            with patch.object(service, "_build_config", return_value=object()):
                with self.assertRaisesRegex(gguf.LocalTTSError, "No audio"):
                    service._generate_wav_no_lock("测试", "uncle_fu")

        ensure_loaded.assert_called_once_with()
        cpu_engine.shutdown.assert_not_called()
        cpu_engine.stream.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
