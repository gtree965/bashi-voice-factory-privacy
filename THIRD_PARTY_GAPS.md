# 第三方许可与分发缺口

日期：2026-09-12。核查 ZIP：v0.1.4，SHA-256 `7b81238fae2e77d4e810b6f7afbfd3fc0b3183e8cf6a3086cdb3d2588c6cf7d4`。

**结论：不能结案为“发行许可核查通过”。** 文件盘点和若干来源比对已完成；阻断修复、许可映射与部分环境复现仍未完成。本清单的阻断是内部放行条件，不意味着已收到组委会否决，也不把证据不足直接表述为已确定侵权。

## 已取得授权、待发布（原阻断项）

| 编号 | 具体对象 | 依据；两段式边界 |
|---|---|---|
| G01 | `vulkan_backend_spike/Qwen3-TTS-GGUF/qwen3_tts_gguf/inference/*` 及随包 readme/requirements | 上游作者在 issue #31 给出的项目特定公开授权，记录见 `licenses/upstream-qwen3-tts-gguf-permission-2026-09-16.md`。**授权记录已随包，待发布**：阶段 1「授权说明进入仓库」已完成；阶段 2「授权说明随发行包分发」尚未完成——授权记录已纳入 v0.1.5 本地构建并通过最终 ZIP 复验，但 v0.1.5 尚未对外发布。关闭条件里的「进入发行包」指实际对外分发，发布动作不在本单，因此此处不写为关闭 |

## 已关闭（v0.1.5）

| 编号 | 具体对象 | 关闭依据 |
|---|---|---|
| G02 | bin 内 llama/ggml DLL、EXE | 原文已随包（`licenses/llama.cpp-b7798-LICENSE.txt`、`licenses/cpp-httplib-b7798-LICENSE.txt`）；构建门禁已入库（`Assert-StagedLicenseDocsMatchGit`）；最终 ZIP 已复验（`bashi-voice-factory-privacy-v0.1.5-windows.zip`） |
| G03 | Python 目录 `libcrypto-3.dll`、`libssl-3.dll` | 原文已随包（`licenses/OpenSSL-3.0.16-LICENSE.txt`）；构建门禁已入库（`Assert-StagedLicenseDocsMatchGit`）；最终 ZIP 已复验（`bashi-voice-factory-privacy-v0.1.5-windows.zip`） |

## 阻断项

| 编号 | 具体对象 | 已见证据 | 关闭条件；本轮边界 |
|---|---|---|---|
| G04 | `libomp140.x86_64.dll` | 官方 b7798 包字节一致；LLVM 文件元数据不足以确定源码版本/分发条款 | 取得对应构建来源与许可，完成版本映射。LLVM 14 原文仅作参考，不能替代此步骤 |
| G05 | 声称“干净安装后的全部 Python 依赖”这一结论 | 本机 115 项环境含 3 个直接版本偏差，wheel 元数据缺失，额外包混入 | 在隔离环境按真实启动链生成可靠安装记录及依赖清单；本轮未重装，不能将观察清单当发行环境认证 |

## 待核实项

| 编号 | 具体对象 | 待补证据与处理 |
|---|---|---|
| G06 | `llama-server.exe` 嵌入 web UI、其余 EXE 及静态第三方代码 | b7798 CMake 和 package-lock 已取得，但锁文件的开发依赖不等于全部被编入二进制。确认实际嵌入内容与声明；或另开打包单缩小分发范围后重验 |
| G07 | Python 包内 `vcruntime140*.dll`、sqlite 等；wheel 原生库 | 逐项核对综合许可已覆盖部分与未覆盖部分，不凭“缺同名许可证”一律判失败。Microsoft 来源与分发条件待闭合 |
| G08 | `model-custom/` 下载包 | 24 项中 23 个运行资产匹配；本机 README 524 B 与 manifest/在线 720 B 不匹配。历史原模型修订、导出配置、模型许可/声明落点仍待补。Qwen 源码许可证不能替代转换运行时授权 |
| G09 | `models/sensevoice-small-int8/*` | 当前原模型卡指向 FunASR 模型协议 1.1，而非代码 Apache 许可。将转换 checkpoint、对应原协议与出处/作者信息闭合 |
| G10 | `models/parakeet-tdt-0.6b-v2-int8/*` | 原卡和转换卡均 CC-BY-4.0；本机未下载，不能写实际文件已经比对。补精确转换版本及署名/修改标识 |
| G11 | `models/silero_vad.onnx` | 与 sherpa 发布附件匹配，但 v3.1/v4.0 原始模型不匹配。追溯这一 643,854 B 文件的确切版本与许可；不猜 AGPL/MIT |
| G12 | `speaker-diarization/...` pyannote、CAMPPlus、ERes2Net | pyannote 归档有 MIT 原文及来源，gated 条件单列；其余两份模型不能只用 3D-Speaker 代码 Apache 原文放行。补 checkpoint 修订与许可链 |
| G13 | `cuda-runtime-b7798-win-cuda-12.4-x64.zip` | 已取官方托管 manifest；未完整下载/哈希核对该归档。确认三份 NVIDIA DLL 与 ggml-cuda 各自条款、随附声明及实际提取结果 |
| G14 | imageio-ffmpeg 0.5.0 所带 FFmpeg 4.2.2 | 实际构建与 GPLv3-or-later 已核实，wheel 来源已比对；对应源码及第三方静态库的提供方式尚未闭合。特别区分用户从 pip 下载与本项目重新托管整合包 |
| G15 | 45 个 style preview MP3 | 维护者来源声明、manifest 和真实 ZIP 哈希比对已完成；原 seed、模型与运行时哈希、完整生成参数未找到。不能伪造记录，也不能把模型 Apache 许可直接写成输出版权许可 |
| G16 | 五个图片文件、使用手册 PDF、`data/zh_confusion.tsv` | 四张图片的维护者声明已收到；`favicon.ico`、生成工具适用条款、PDF 嵌入字体及词表来源待补。无需公开支付标识内容 |
| G17 | 所有历史发行产物不含实验资产的绝对断言 | 只筛查本地 7 个 ZIP 条目名，不覆盖所有远端历史/分卷/被改名内容。不能勾选“从未进入任何发行产物” |
| G18 | `get-pip.py` 与 115 项元数据中未找到独立许可文件的包 | 捕获实际引导脚本快照；按准确 wheel 查许可证、NOTICE、原生依赖。没找到文件不等于无许可；元数据声明也不等于全部义务已履行 |

## 不单独判为发行阻断的事项

- **EXE 是否未使用：** bin 内 18 个 EXE 共 66,450,432 B。“多余”是体积/范围问题，不能直接推导许可违法；实际包含而未履行声明义务才是需要处理的缺口。本轮没有删除任何文件。
- **页脚文案：** 维护者确认，旧页脚“个人和教育用途均可免费使用”是为保持界面一致而沿用自同作者另一款产品的文案，不能用来描述本项目代码或整个发行物的许可范围；本条不对该产品或其所用外部服务的条款作任何推断。源码中的页脚已改为“项目代码：MIT 许可证；模型与第三方组件遵循各自许可条款”，不对整个发行包作统一授权承诺。v0.1.0–v0.1.4 已发布的旧包仍含旧文案，需由后续重打包补正。
- **试听目录：** 当前 `build_portable_zip.ps1` 已有 `Assert-StagedStylePreviewsMatchGit`。不能继续说“当前构建不查 Git”；该门禁检查文件集合，不证明素材来源或再分发权。45 个真实发行 MP3 已逐文件比对。
- **来源 URL：** 下载说明可证明声明来源；本次另外完成官方归档比对后，才把相关二进制标为未修改。未做比对的组件仍不作该结论。

## 改进建议（不阻断发行）

- 上游仓库仍无标准根 LICENSE（`license` 字段为空；默认分支根目录无 `LICENSE*` / `COPYING*` / `NOTICE*`；2026-09-17 两次只读检查一致）。当前分发依据是作者在 issue #31 的项目特定公开授权记录，而不是标准许可证。**此项不再是发行阻断**；若上游后续补充许可证文件或变更授权，按新证据更新记录并重新评估。

## 已知陈旧说明（随 G05 重生成）

- `licenses/inventory/release-files.csv`、`release-summary.json` 等描述的是 **v0.1.4** 的 207 个条目，**不适用于 v0.1.5**（v0.1.5 新增 33 份许可材料）。
- `licenses/inventory/license-file-hashes.json` 中 `licenses/README.md` 记为 2,690 B，实际为 2,975 B（`48c478f` 后未重生成）。
- 以上两项均在隔离环境随 G05 一并重生成；本单不改 `licenses/inventory/` 的任何字节。

## 建议下一步

G01 的授权记录已纳入 v0.1.5 待发布包并通过最终 ZIP 复验，待实际对外发布后关闭。G02/G03 已随 v0.1.5 落包并关闭（原文随包、构建门禁入库、最终 ZIP 已复验）。G04 先取得精确条款；G05 在隔离环境重建安装记录与依赖清单，并重生成上节的陈旧条目。模型与 CUDA 继续按原始模型、转换产物、实际下载文件三层追溯。本单只做许可材料落包与状态更新，未联系上游、未替换组件、未删减文件。
