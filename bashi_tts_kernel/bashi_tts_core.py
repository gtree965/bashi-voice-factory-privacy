"""
巴适声工厂 (Bashi Voice Studio) 离线 TTS 核心引擎
Bashi TTS Core Engine (Offline)

基于:
- Qwen3-TTS 1.7B CustomVoice
- 硬件自适应 (CUDA/XPU/MPS/CPU) 
- PyTorch 线程锁定并发控制 (只占用物理核心，抵制超线程负优化)
- 纯净且无感的流式分块输出 (Streaming via yield)
"""

import os
import multiprocessing

try:
    from logging_setup import get_logger
except ImportError:  # kernel used standalone / outside the app tree
    import logging

    def get_logger(name):
        return logging.getLogger(name)


logger = get_logger(__name__)

# ---------------------------------------------------------
# [引擎最底层环境初始化]
# 务必在 import torch 之前锁定线程，防止多核资源抢占与缓存失效
# ---------------------------------------------------------
cpu_count = multiprocessing.cpu_count()
optimal_threads = min(8, max(2, cpu_count // 2))

os.environ["OMP_NUM_THREADS"] = str(optimal_threads)
os.environ["MKL_NUM_THREADS"] = str(optimal_threads)
os.environ["OPENBLAS_NUM_THREADS"] = str(optimal_threads)

import torch
import warnings
warnings.filterwarnings('ignore')

def auto_detect_device():
    """根据运行环境自动匹配最优推断运算卡
    
    检测优先级: CUDA > XPU > MPS > DirectML > CPU
    DirectML 可通过 pip install torch-directml 启用，支持 AMD/Intel 老显卡。
    """
    if torch.cuda.is_available():
        logger.info("[Auto-Device] Detected NVIDIA CUDA GPU.")
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        logger.info("[Auto-Device] Detected Intel NPU/XPU.")
        return "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        logger.info("[Auto-Device] Detected Apple Silicon MPS.")
        return "mps"
    # DirectML: 支持任何 DirectX 12 GPU (AMD Polaris/RDNA, Intel Arc 等)
    # 需要 pip install torch-directml，且 PyTorch 版本 ≤ 2.3.1
    try:
        import torch_directml
        dml_device = torch_directml.device()
        logger.info(
            "[Auto-Device] Detected DirectML device: %s (AMD/Intel GPU via DX12).",
            dml_device,
        )
        return dml_device  # 返回 torch.device 对象
    except (ImportError, Exception):
        pass
    logger.info(
        "[Auto-Device] Fallback to CPU mode (Locked to %s Physical Threads).",
        optimal_threads,
    )
    return "cpu"

GLOBAL_DEVICE = auto_detect_device()

if GLOBAL_DEVICE == "cpu":
    torch.set_num_threads(optimal_threads)

import re
import time
import numpy as np
from pathlib import Path

# 尝试导入核心组件，失败则提示 (依赖于 qwen_tts 库和本包内的 zh_normalizer_lite)
try:
    from qwen_tts import Qwen3TTSModel
except ImportError:
    logger.warning(
        "Could not import qwen_tts. Make sure you are in the correct conda environment."
    )

try:
    from .zh_normalizer_lite import normalize_chinese_text
except ImportError:
    try:
        from zh_normalizer_lite import normalize_chinese_text
    except ImportError:
        logger.warning("Could not import zh_normalizer_lite. Ensure the package is complete.")
        def normalize_chinese_text(text, options=None): return text

class BashiTTSEngine:
    def __init__(self, model_dir=None, device=None, dtype=None):
        if model_dir is None:
            model_dir = Path(__file__).resolve().parent / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
        self.device = device if device else GLOBAL_DEVICE
        
        # dtype 决策：None = 自动选择，显式传值 = 尊重用户选择
        if dtype is not None:
            self.dtype = dtype
        else:
            # GPU 自动用 bfloat16 提速，CPU 保持 float32 保稳定
            is_gpu = (str(self.device) != "cpu")
            self.dtype = torch.bfloat16 if is_gpu and hasattr(torch, "bfloat16") else torch.float32
            
        # 解析本地模型路径 (支持 HuggingFace cache 作为 fallback)
        self.resolved_model_dir = self._resolve_model_path(model_dir)
        
        # 强制使用离线模式（如果本地已有文件）
        if os.path.isdir(self.resolved_model_dir):
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        
        device_label = str(self.device).upper() if isinstance(self.device, str) else str(self.device)
        logger.info(
            "Loading Qwen3-TTS | Device: %s | Dtype: %s | Path: %s",
            device_label,
            self.dtype,
            self.resolved_model_dir,
        )
        t0 = time.time()
        self.model = Qwen3TTSModel.from_pretrained(
            self.resolved_model_dir, 
            device_map=self.device, 
            dtype=self.dtype,
            attn_implementation="sdpa" # [Option 3] 启用 PyTorch 内存优化版点积注意力机制
        )
        logger.info("Model loaded successfully in %.2fs", time.time() - t0)
        
        # 情绪锚点字典
        self.anchor_phrases = {
            "庄重长者": "请您听我说，",  
            "平缓陈述": "从前啊，",    
            "活泼轻快": "太棒了吧，",  
            "中性默认": "好的，",        
        }

    def _resolve_model_path(self, model_name: str) -> str:
        if os.path.isdir(model_name):
            return model_name
        hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
        model_dir = "models--" + model_name.replace("/", "--")
        snap_dir = hf_cache / model_dir / "snapshots"
        if snap_dir.exists():
            snaps = sorted(snap_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if snaps:
                return str(snaps[0])
        return model_name
        
    def _set_seed(self, seed=42):
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        np.random.seed(seed)
        
    def _normalize_audio(self, audio_array, target_dBFS=-18.0):
        if len(audio_array) == 0:
            return audio_array
        rms = np.sqrt(np.mean(audio_array**2))
        if rms == 0:
            return audio_array
        current_dBFS = 20 * np.log10(rms)
        gain = 10 ** ((target_dBFS - current_dBFS) / 20)
        return np.clip(audio_array * gain, -1.0, 1.0)

    def _split_stream_text(self, text: str, max_chars: int = 20):
        """Split text for internal PyTorch streaming without depending on Flask routes."""
        sentence_pattern = r'([^.!?。！？।؟;；]+[.!?。！？।؟;；]+[”’』」）】》]*)'
        chunks = []

        for paragraph in text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            sentences = re.findall(sentence_pattern, paragraph)
            remaining = re.sub(sentence_pattern, "", paragraph).strip()
            if remaining:
                sentences.append(remaining)
            if not sentences:
                sentences = [paragraph]

            current_chunk = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                if len(current_chunk) + len(sentence) > max_chars:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    current_chunk += sentence

            if current_chunk:
                chunks.append(current_chunk.strip())

        return [chunk for chunk in chunks if chunk.strip()]

    def generate_stream(
        self, 
        text: str, 
        speaker: str = "Uncle_Fu", 
        language: str = "Chinese",
        anchor_type: str = "庄重长者",
        anchor_mode: str = "first_only",
        target_dBFS: float = -18.0,
        temperature: float = 0.7,
        top_p: float = 0.85,
        subtalker_temperature: float = 0.7,
        subtalker_top_p: float = 0.85,
        seed: int = 42,
        instruct: str = "",
        progress_callback = None
    ):
        """
        流式 Generator 生成器方案。
        
        Args:
            instruct: 自然语言风格/情绪控制指令；空字符串表示 neutral。
            anchor_mode: 锚点策略
                - "first_only": 历史默认值；现在等同默认裸跑，避免 anchor trim 吃掉首字
                - "all": 每块都拼锚点并裁掉前缀（慢，且仅用于显式诊断/实验）
        
        Yields:
              (sr, audio_chunk_array)
        """
        normalized_text = normalize_chinese_text(text)
        if not normalized_text.strip():
            return
            
        # 1. 选择锚点短语。默认 first_only 不再使用 anchor：
        # 单 chunk 和多 chunk 首块都已被听感验证会遇到 speaker-specific trim artifact。
        anchor_phrase = self.anchor_phrases.get(anchor_type, self.anchor_phrases["中性默认"])
        
        # 2. 面向 TTFB 和 Streaming 的高频切分
        # 预处理：将段落换行转换为句号，防止 \n\n 被 TTS 模型读为文档结束导致内容丢失
        clean_text = re.sub(r'\n+', '。', normalized_text)   # \n -> 句号
        clean_text = re.sub(r'[。]{2,}', '。', clean_text)   # 。。-> 。 (去重)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip() # 多余空白

        # [Option 2] 将原来 35 个字符才切分的上限压低到 20，大幅降低 O(N^2) 算力惩罚，并缩减首字等待时间(TTFB)。
        # The splitter mirrors the route-level shadowing splitter's sentence-boundary
        # behavior so non-Chinese text without CJK punctuation still produces chunks.
        chunks_text = self._split_stream_text(clean_text, max_chars=20)
        total_chunks = len(chunks_text)

        will_use_anchor = anchor_mode == "all"
        prefix_sr = 24000
        trim_samples = 0
        if will_use_anchor:
            self._set_seed(seed)
            prefix_wav, prefix_sr = self.model.generate_custom_voice(
                text=anchor_phrase, 
                speaker=speaker, 
                language=language, 
                temperature=temperature, 
                top_p=top_p,
                subtalker_temperature=subtalker_temperature,
                subtalker_top_p=subtalker_top_p
            )
            trim_samples = len(prefix_wav[0]) + int(0.05 * prefix_sr)
        
        # 定义淡入淡出参数 (取代旧版的等待型交叉淡入淡出)
        fade_ms = 40
        fade_samples = int(prefix_sr * fade_ms / 1000)

        # 3. 流式运算与推送
        for idx, chunk_text in enumerate(chunks_text):
            if progress_callback:
                progress_callback(idx + 1, total_chunks, chunk_text)
            
            # --- 强力防护 ---
            # 1. 清理潜在残留的空白字符串
            safe_text = chunk_text.strip()
            if not safe_text:
                continue
            # 2. 强制将非闭环标点转为句号，防止低温度下模型在逗号悬停报错（产生长达十几秒的静音幻觉）
            safe_text = re.sub(r'[，、；：,;:]$', '。', safe_text)
            
            # Anchor is now opt-in: default generation preserves first-token onsets.
            use_anchor = anchor_mode == "all"
            
            if use_anchor:
                combined_text = anchor_phrase + safe_text
                self._set_seed(seed)
                wavs, sr = self.model.generate_custom_voice(
                    text=combined_text,
                    speaker=speaker,
                    language=language,
                    instruct=instruct,
                    temperature=temperature,
                    top_p=top_p,
                    subtalker_temperature=subtalker_temperature,
                    subtalker_top_p=subtalker_top_p,
                    repetition_penalty=1.1, # 增加重复惩罚，防止“拉长音”和死板停顿
                    max_new_tokens=450      # 设置硬上限，彻底防止死锁产生数分钟的无声幻觉
                )
                raw_audio = wavs[0]
                # 删除前置锚点音轨
                if len(raw_audio) > trim_samples:
                    trimmed_audio = raw_audio[trim_samples:]
                else:
                    trimmed_audio = raw_audio
            else:
                # 裸跑模式：不拼锚点，不需要 trim
                self._set_seed(seed)
                wavs, sr = self.model.generate_custom_voice(
                    text=safe_text,
                    speaker=speaker,
                    language=language,
                    instruct=instruct,
                    temperature=temperature,
                    top_p=top_p,
                    subtalker_temperature=subtalker_temperature,
                    subtalker_top_p=subtalker_top_p,
                    repetition_penalty=1.1,
                    max_new_tokens=450
                )
                trimmed_audio = wavs[0]
                
            # RMS 音量归一
            normalized_audio = self._normalize_audio(trimmed_audio, target_dBFS)
            
            # 仅尾部施加淡出，防止截断咔哒声
            # 注意：不做 fade-in，因为会吃掉每个 chunk 首字的发音起音
            if len(normalized_audio) >= fade_samples:
                fade_out_curve = np.linspace(1, 0, fade_samples)
                normalized_audio[-fade_samples:] *= fade_out_curve

            # 即时 Yield 推给前端 Gradio
            yield (prefix_sr, normalized_audio)

    # 兼容老的非流式 API 保底
    def generate(self, text: str, **kwargs):
        chunks = []
        sr = 24000
        for loop_sr, chunk in self.generate_stream(text, **kwargs):
            sr = loop_sr
            chunks.append(chunk)
        if not chunks:
            return np.array([], dtype=np.float32), sr
        return np.concatenate(chunks), sr

if __name__ == "__main__":
    import soundfile as sf
    test_text = "今天的工作流程比预期顺利。会议结束后，团队简单总结了一下要点，大家分头继续推进各自的任务。"
    engine = BashiTTSEngine()
    
    print("Testing generate_stream behavior...")
    total_audio = []
    sr = 24000
    for chunk_sr, chunk_data in engine.generate_stream(test_text):
        sr = chunk_sr
        total_audio.append(chunk_data)
        print(f" -> Yielded chunk of {(len(chunk_data)/sr):.2f} seconds.")
        
    final_audio = np.concatenate(total_audio)
    sf.write("core_test_output_streamed.wav", final_audio, sr)
    print("Stream test completed!")
