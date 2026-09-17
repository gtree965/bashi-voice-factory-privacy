# 许可原文与适用范围

这些文件保留原作者版权、许可条件及原始内容。本项目没有为规避提交检查而删除合法权利人、供应商或模型名称。

**这些文件尚未写入已发布的 v0.1.4 ZIP。** 它们也不能补足没有找到的授权。具体缺口见 [清单](../THIRD_PARTY_GAPS.md)。

| 文件 | 来源和适用范围 |
|---|---|
| `llama.cpp-b7798-LICENSE.txt` | ggml-org/llama.cpp 的 b7798 LICENSE；对应包内已与官方比对的 llama/ggml 二进制。静态链接第三方内容仍需单独核对 |
| `cpp-httplib-b7798-LICENSE.txt` | 同一 b7798 源码树 vendor/cpp-httplib/LICENSE；server 构建引用该组件 |
| `OpenSSL-3.0.16-LICENSE.txt` | openssl/openssl 的 openssl-3.0.16 LICENSE.txt；对应包内 3.0.16 DLL |
| `Python-3.12.10-LICENSE.txt` | 从被核查 ZIP 原样提取，且与 Python 官方嵌入式包一致；包含历史 Python 许可与部分第三方声明 |
| `pyannote-segmentation-3.0-converted-LICENSE.txt` | 本机转换归档解压目录所带 CNRS MIT；其哈希在归档文件清单中可复核 |
| `Qwen3-TTS-source-LICENSE.txt` | 官方 Qwen3-TTS 源码库许可证；不能覆盖 HaujetZhao 转换运行时的全部原创代码，也不能替代模型精确版本映射 |
| `imageio-ffmpeg-0.5.0-LICENSE.txt` | 本机已安装包装层的 BSD-2-Clause；不覆盖随 wheel 携带的 FFmpeg EXE |
| `FFmpeg-4.2.2-COPYING.GPLv3.txt` | FFmpeg n4.2.2 原文；实际 EXE 自报 GPLv3-or-later。对应源码交付方式尚需审查 |
| `references/LLVM-14.0.6-OpenMP-LICENSE.txt` | **仅参考**。尚未证明包内 libomp140 对应此源码版本，不得标为已闭合许可 |
| `references/Silero-v4.0-LICENSE.txt` | **仅参考**。该 tag 的模型与实际 VAD 哈希不同，不得自动套用 |
| `references/3D-Speaker-source-LICENSE.txt` | **仅参考代码许可**。模型 checkpoint 条款与转换谱系待追溯 |
| `references/FunASR-model-license-1.1.txt` | SenseVoice 当前原模型卡指向的条款快照；实际转换版本映射仍待补。不是 Apache-2.0 |
| `upstream-qwen3-tts-gguf-permission-2026-09-16.md` | HaujetZhao/Qwen3-TTS-GGUF 作者在 issue #31 给出的项目特定公开授权记录；**不是许可证文件**，适用范围与解读边界见文件内说明 |

没有创建名为“Qwen3-TTS-GGUF LICENSE”的替代授权文件，也没有用自写 NOTICE 冒充上游 NOTICE；现已收录作者本人的授权记录，见上表——该记录是公开授权说明，不是许可证文件。当前只收录已找到的原文及明确标注的参考文件；将来按实际组件要求保留其原有 NOTICE。

[文件哈希](inventory/license-file-hashes.json) · [取得来源与结果](inventory/source-evidence.json) · [第三方总表](../THIRD_PARTY.md)

`inventory/` 是审计数据，不是安装清单。尤其 115 项 Python 环境观察记录包含额外包及版本偏差，不能据此生成发行 requirements。
