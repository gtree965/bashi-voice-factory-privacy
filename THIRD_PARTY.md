# 第三方组件与分发清单

核查日期：2026-09-12。范围：巴适声工厂·隐私版 v0.1.4 Windows 发行包及其下载入口。

**当前状态：盘点已形成，发行许可核查尚未通过。** 本文件和 `licenses/` 是后续补正的工作成果，尚未进入已发布压缩包；不能据此声称旧包的缺口已经修复。已确认的缺口与待核实事项见 [缺口清单](THIRD_PARTY_GAPS.md)。

项目自身代码采用 [MIT](LICENSE)。第三方代码、模型、二进制和素材保留各自条款；项目的 MIT 不覆盖所有下载组件，也不自动决定生成音频或图片的权利。

## 核查对象与证据

- 发行包：`bashi-voice-factory-privacy-v0.1.4-windows.zip`，62,071,443 B。
- SHA-256：`7b81238fae2e77d4e810b6f7afbfd3fc0b3183e8cf6a3086cdb3d2588c6cf7d4`。
- 207 个 ZIP 条目：202 个文件、5 个目录，已全部逐条归类。嵌入式 `python312.zip` 内部条目另行保存为核查证据；这不等于对所有嵌入代码、字体和静态链接依赖完成逐项许可审查。
- 逐文件大小、哈希、来源、许可状态、修改情况、分发方式与声明要求见 [发行文件 CSV](licenses/inventory/release-files.csv)。
- 上游文本的取得地址、内容哈希与失败记录见 [来源证据](licenses/inventory/source-evidence.json)。使用浮动地址的资料仅代表核查日快照，不能替代历史产物的准确版本追溯。
- `已核实` 仅指对应行描述的事实；`待核实` 表示证据未闭合；`阻断` 表示本次内部发行核查不予放行，不是对赛事结果的判断。

## A. 随发行包分发

| 组件 | 实际数量/版本 | 许可与修改情况 | 状态及处理 |
|---|---|---|---|
| 项目代码与文档 | 47 个条目；另有词表与音色目录 | 项目 MIT；组内 PDF 的嵌入字体尚未单独核查 | 待核实附带素材来源；不是逐项法律放行 |
| 嵌入式 Python 包 | 35 个文件，3.12.10 | 35/35 与官方 ZIP 原始字节相同；已随包带 Python 综合许可证，内含部分第三方声明 | Python 来源已核实；OpenSSL 等分项见下 |
| OpenSSL | `libcrypto-3.dll`、`libssl-3.dll`，3.0.16 | 二进制版本字符串与 CPython 3.12.10 构建脚本对应；Apache-2.0 | 旧包未发现 OpenSSL 许可正文；已准备对应文件，尚待打包补正 |
| Python 所带其他运行库 | `libffi-8.dll`、`sqlite3.dll`、`vcruntime140*.dll` 等 | 必须分别判断；Python 综合许可已经包含 libffi 等内容，不能仅因无单独文件就判全部缺失 | Microsoft 运行库的适用分发条款等仍待逐项闭合 |
| llama.cpp/ggml 二进制 | bin 内 38 个：20 DLL + 18 EXE；b7798 | 全部与官方 Vulkan x64 包字节一致；MIT 及所含第三方条款 | 旧包未附 ggml 作者的 MIT 声明；阻断，待打包补正 |
| OpenMP | bin 内另有 `libomp140.x86_64.dll` | 与官方包相同；文件元数据为 LLVM、FileVersion `20140926`、ProductVersion `5.0` | 精确源版本及适用条款未确定；不能从文件名推定 LLVM 14 |
| llama-server 嵌入内容 | 已分发 `llama-server.exe` | b7798 CMake 将 `index.html.gz` 等嵌入目标程序；来源树有前端依赖与 cpp-httplib | 依赖许可范围待审；已取 cpp-httplib MIT。仅补主 LICENSE 不代表其余静态内容全覆盖 |
| Qwen3-TTS-GGUF 转换运行时源码 | 27 个文件，固定提交见逐文件表 | `Custom permission — GitHub issue #31`；26 个仅换行归一化后一致；`inference/llama.py` 有修改，对应本项目日志补丁 | **授权已取得，待落包**：作者本人公开授权，见 `licenses/upstream-qwen3-tts-gguf-permission-2026-09-16.md`；待随发行包分发该说明后闭合。边界：原文只写 use，修改与再分发为整体解读，不是许可证文件 |
| 风格试听 | 45 个 MP3 + 1 个 manifest | 45/45 与工作区音频哈希一致；维护者确认全部由项目 CustomVoice 生成 | 来源声明已记录；原始 seed、模型/运行时哈希及完整生成参数未闭合 |
| 图片 | 5 个：JPG、PNG 和 ICO | 维护者确认四个 JPG/PNG 自制或通过生成工具制作 | `favicon.ico` 未单独确认；工具条款及必要来源记录待补 |
| 数据与音色元数据 | `data/zh_confusion.tsv`、`bashi_tts_kernel/speakers.json` | 项目专用表和目录；上游模型标识与实际参考音频权利不能混同 | 词表及描述来源记录待补 |

整包合计 29 DLL、20 EXE，包含 Python；不是全部来自 llama.cpp。bin 内为 21 DLL、18 EXE，共 39 个二进制，另外有一份下载说明。[完整比对](licenses/inventory/official-binary-comparison.json)

18 个 bin EXE 合计 66,450,432 B（约 63.37 MiB）。是否可以删减需要调用路径和打包验收，本次不删除，也不把“未使用”本身当作违反许可的证据。无需的程序仍可能扩大分发审查范围。

Qwen3-TTS-GGUF 固定树内存在 `Qwen3-TTS-main/LICENSE`、`ref/llama.cpp/LICENSE` 等嵌套文件，但没有证据表明它们给转换运行时的全部原创代码授权。本项目不以补一份 Qwen 或 llama.cpp 许可证替代这项缺口。[源码差异](licenses/inventory/upstream-source-comparison.json) · [固定树许可路径](licenses/inventory/upstream-license-paths.json)

## B. 首次准备或用户操作时下载

### Python 依赖与实际环境

发行包 `requirements.txt` 实际为 **19 条**依赖，启动器另指定 `qwen-tts==0.1.1 --no-deps`、`setuptools==79.0.1`、`wheel==0.45.1`，并重装已在清单中的 DirectML 包。pip 引导脚本也需纳入记录；不能将“19+3”表述为 requirements 有 22 条。

本次读取真实嵌入式环境的 **115 个 distribution 元数据**，逐项导出版本、声明许可、许可文件路径和哈希。依据该环境元数据重建的依赖闭包包含 67 个已安装项，另有 48 项不在该闭包；闭包不是干净解析安装的证明。

已经观察到：setuptools 实装 82.0.1、要求 79.0.1；sox 实装 1.4.1、要求 1.5.0；torchaudio 实装 2.11.0、要求 2.10.0；未找到 wheel distribution。另有普通 onnxruntime、gradio 等额外安装项。**不把这些全部标为产品交付，也不把此环境宣称为已验收发行环境。** 本次未修复或重装环境。

- [115 项观察清单](licenses/inventory/observed-python-packages.csv)
- 完整元数据与许可文件哈希：`observed-python-metadata.json`，274,984 B，SHA-256 `fb53bdde7568a1b0bd740eec56c8fea30fed04583a6a5df985183c8cf67a5d92`。该文件是机器生成的原始元数据转储，属仓库外原始执行证据，未随仓库发布；核对时按此哈希校验，不要从仓库内查找。
- [依赖范围、偏差和缺项](licenses/inventory/dependency-scope.json)

Python 元数据不能覆盖全部原生代码。torch、numpy、llvmlite、soundfile、sounddevice 等还需检查各 wheel 的第三方库声明；本次已记录找到的许可文件，未对每个 wheel 的所有二进制作来源比对。未找到独立 LICENSE 文件的元数据项也不能直接判无许可。

### FFmpeg

实际二进制是 `imageio_ffmpeg/binaries/ffmpeg-win64-v4.2.2.exe`，SHA-256 `404fdd541eecc577d8f24bf9a976f1e4209f4292022a41c01f5cc2f1b0d375ac`；与 PyPI 官方 imageio-ffmpeg 0.5.0 Windows wheel 内文件字节一致。

包装层为 BSD-2-Clause；该 EXE 的 `-L` 输出为 **GPL-3.0-or-later**，`-version` 显示 `--enable-gpl --enable-version3`。两者分别记录，不能用包装层许可证代替二进制许可证。FFmpeg 官方说明构建选项会影响适用许可。[官方说明](https://ffmpeg.org/legal.html)

本项目当前通过 pip 下载该 wheel，v0.1.4 ZIP 本身没有该 EXE。后续若制作包含安装环境的整合包，需要另行闭合二进制及对应源码的提供方式。本次没有据此推导“整个应用必须更换为 GPL”。[构建实测](licenses/inventory/ffmpeg-version.txt) · [许可输出](licenses/inventory/ffmpeg-license.txt) · [官方 wheel 比对](licenses/inventory/ffmpeg-wheel-verification.json)

### 模型、转换产物与 CUDA

| 组件 | 来源与核查结果 | 仍需闭合 |
|---|---|---|
| CustomVoice GGUF/ONNX 包 | ModelScope 自建包 manifest `20260507`，原模型指向 Qwen CustomVoice；当前原模型卡标 Apache-2.0；23 个本机运行资产哈希匹配 manifest，另 1 个 README 不匹配 | 本机 README 为 524 B，在线与 manifest 为 720 B；原 checkpoint 的精确修订与本次导出链、下载包许可/声明仍待补。GGUF 量化与 ONNX 转换不能写成与原权重逐字节“未修改” |
| SenseVoice Small INT8 | 本机模型与下载器 SHA 匹配；转换卡指向 SenseVoice 项目；当前原模型卡为 `other/model-license`，链接 FunASR MODEL_LICENSE 1.1 | 不能套用代码的 Apache 许可；需闭合实际转换 checkpoint 对应条款与来源声明 |
| Parakeet TDT 0.6B v2 INT8 | 原模型卡与转换卡均标 CC-BY-4.0；下载器固定各文件哈希 | 本机未发现该模型，未作实际文件比对；需对应版本和量化转换署名记录 |
| Silero VAD | 本机 643,854 B 文件与 sherpa-onnx 发行附件哈希一致 | 所取 Silero v3.1/v4.0 原模型均不与其匹配；不得直接套用这些 tag 的 MIT，也没有证据支持“该文件是 AGPL” |
| pyannote segmentation 3.0 | 已下载并核对转换归档 SHA；归档内有 CNRS MIT 原文及指向原模型的 README | 原模型访问条件单列；转换具体上游修订仍待补。不将 gated 访问等同于非商业许可 |
| 3D-Speaker CAMPPlus 与 ERes2Net | 两份均为产品下载器列出的文件，本机哈希匹配 | 原代码库 Apache-2.0 仅是代码证据；两份 checkpoint 的精确版本和权重条款仍待追溯 |
| CUDA add-on | 在线 manifest 固定 b7798、CUDA 12.4，列四个 DLL 及各哈希 | 此次未下载 595 MB 归档作完整比对；须核实 SDK 分发条件与随附第三方声明，不能将三个 NVIDIA DLL 标为 MIT |

[40 条下载产物记录](licenses/inventory/download-files.csv) 包含模型文件、CUDA 提取文件、FFmpeg 及 pip 引导。对归档下载，归档哈希与解压后模型哈希分开解释，不能互相比较。

来源：[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)、[SenseVoice 模型卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)、[FunASR 模型条款](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)、[Parakeet 模型卡](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2)、[pyannote 许可与访问说明](https://huggingface.co/pyannote/segmentation-3.0)、[CUDA 12.4 条款](https://docs.nvidia.com/cuda/archive/12.4.0/eula/index.html)。原始与转换来源各自记录，没有将其中任一来源的许可自动覆盖另一来源。

## C. 仅开发、测试或实验

- 构建工具：`requirements-build.txt` 中的 pypdf；不属于发行 ZIP 的运行依赖。本次核查用的工具与下载对照包也不属于产品分发。
- 实验 Base/VoiceDesign 导出、上游其他版本 GUI/模型、语料及私人参考音频：不得因为本机存在就列为 A/B。原密封实验目录未读取答案、映射或执行生成。
- 本机 `models/fire-red-asr-large-int8/` 存在模型文件，但 v0.1.4 下载器注册表和 ZIP 不包含它；列为本地残留/实验项，非产品下载能力。
- 本机环境中未被声明依赖闭包覆盖的包仅记录“观察到额外安装”，不凭这一点确定其实际用途。

检查了本地 7 个 ZIP（含一个 CUDA 探针包）的条目名，未发现指定实验目录名。**这只是已检查归档的路径筛查，不能证明全部历史发布包从未混入实验内容，也不能识别被改名的文件。** 历史完整性仍待核实。[范围记录](licenses/inventory/historical-name-screen.json)

## 素材与后续分发

维护者于 2026-09-12 确认：45 个试听 MP3 由项目 CustomVoice 模型生成；`bashi_logo_v2.jpg`、`favicon.png`、`alipay.jpg`、`wechat-pay.png` 为自行制作或使用生成工具制作。此为来源声明，不虚构不存在的原始生成日志或独立权属证明。支付二维码不复制到本清单，清单只记录文件路径和哈希。[声明](licenses/inventory/user-asset-declaration.json) · [45 条音频记录](licenses/inventory/preview-provenance.csv)

建议后续发行包将 `THIRD_PARTY.md`、`THIRD_PARTY_GAPS.md`（仍有未决事项时）与 `licenses/` 放在解压根目录，并为可选模型/CUDA 包提供相应许可文件。**本次没有修改构建脚本、下载器、UI 或旧 ZIP，以上只是明确的打包落点建议。** 不以文件已加入工作区替代真实发行包复验。
