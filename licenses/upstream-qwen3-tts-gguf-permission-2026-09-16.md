# 上游授权记录：HaujetZhao/Qwen3-TTS-GGUF 转换运行时代码

**这是授权记录，不是许可证文件。** 本文件记录上游仓库作者在公开 issue 中给出的项目特定公开授权（project-specific public permission），作为本项目分发其原创代码的依据说明；它不发布、也不替代任何标准许可证。

- 授权人：GitHub 登录名 `HaujetZhao`（仓库 owner）。
- 授权形式：issue 评论形式的非正式授权说明；没有许可证正文，也没有担保与责任条款。
- 适用对象：上游作者本人原创的代码（`qwen3_tts_gguf/` 及随包 `readme.md`、`requirements.txt` 等，对应固定提交 `dc8950d7…`）。
- 不适用对象：仓库内 vendored 的第三方组件（Qwen3-TTS、llama.cpp/ggml 等），它们按各自许可证单独履行，见[第三方总表](../THIRD_PARTY.md)。

## 1. 出处

| 项 | 值 |
|---|---|
| 仓库 | `HaujetZhao/Qwen3-TTS-GGUF`（GitHub 公开仓库） |
| issue | #31，标题「请明确 Qwen3-TTS-GGUF 原创代码的许可证」 |
| issue 链接 | https://github.com/HaujetZhao/Qwen3-TTS-GGUF/issues/31 |
| 发帖 | GitHub 用户 `gtree965`（本项目维护方），2026-09-16T08:17:45Z（北京时间 2026-09-16 16:17:45） |
| 回复 | `HaujetZhao`，`author_association = OWNER`，2026-09-16T08:20:52Z（北京时间 2026-09-16 16:20:52），发帖后约 187 秒 |
| 评论链接 | https://github.com/HaujetZhao/Qwen3-TTS-GGUF/issues/31#issuecomment-5694369401 |
| 评论 id | `5694369401` |
| 未编辑的证据 | `updated_at == created_at`；GraphQL `userContentEdits.totalCount = 0`、`lastEditedAt = null` |

## 2. 原文

**原始字节（API 返回的 markdown 源，含 `&nbsp;` 实体；UTF-8 共 150 B）：**

```text
Please&nbsp;feel&nbsp;free&nbsp;to&nbsp;use&nbsp;all&nbsp;the&nbsp;things&nbsp;I&nbsp;have&nbsp;written&nbsp;without&nbsp;any&nbsp;restrictions.&nbsp;
```

**渲染形式（`&nbsp;` 渲染为空格；原串末尾还有一个 `&nbsp;`，渲染为结尾空格）：**

```text
Please feel free to use all the things I have written without any restrictions.
```

## 3. 适用范围（本项目对其含义的解读）

- 覆盖：上游作者本人写作的代码与随包文档；即上述固定提交所对应的随包转换运行时（`qwen3_tts_gguf/` 及 `readme.md`、`requirements.txt` 等，共 27 个文件）。
- 本项目使用方式：随 Windows 便携发行包分发上述代码；其中 `inference/llama.py` 含本项目的日志等级补丁（本项目对该文件的唯一修改）。
- 不覆盖：仓库内 vendored 的 Qwen3-TTS、llama.cpp/ggml 等第三方组件；原文措辞 “all the things I have written” 亦自限于作者本人写作。

## 4. 解读边界（必须与授权一起理解）

1. 原文只出现 “use”，**未逐字写明 modify / redistribute**；我们是依据 “without any restrictions” 作整体解读。
2. 这是 issue 评论形式的非正式授权，**不是许可证文件**，没有担保与责任条款。
3. 原文未限定版本；我们据 “all the things I have written” 理解为涵盖固定提交 `dc8950d7…`，**这是解读不是上游原话**。
4. 原回复**未写明不可撤销性**；本项目**不对其可撤销性作法律结论**。若上游补充或变更可公开核验的授权文件，以新证据更新本记录，并重新评估后续发行。

## 5. 复核方法（只读）

```bash
gh api repos/HaujetZhao/Qwen3-TTS-GGUF/issues/31
gh api "repos/HaujetZhao/Qwen3-TTS-GGUF/issues/31/comments?per_page=100"
```

截至 2026-09-17（两次只读检查）结果一致：仓库 `license` 字段为 `null`；默认分支根目录无 `LICENSE*` / `COPYING*` / `NOTICE*` 文件；上述回复未被编辑。若其中任何一项发生变化（尤其出现根目录许可证文件），本记录的结论按新证据重新评估。

状态注记：本项目已于 2026-09-17 在该 issue 中请求作者补充仓库根目录许可证文件；截至上述检查上游未回复。本记录的授权依据是上表 OWNER 回复本身，不依赖该请求的结果。
