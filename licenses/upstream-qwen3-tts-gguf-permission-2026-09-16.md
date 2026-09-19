# 上游授权演进记录：HaujetZhao/Qwen3-TTS-GGUF 转换运行时代码

**这是授权记录，不是许可证文件。** 本文件记录上游仓库作者在公开 issue 中给出的项目特定公开授权（project-specific public permission），作为本项目分发其原创代码的依据说明；它不发布、也不替代任何标准许可证。

本记录按时间记录授权演进：先有 issue #31 的公开授权（2026-09-16），后有仓库根目录 MIT（2026-09-19，提交 `74feb581`）。两者并存、互为补充；MIT 原文另见同目录 `Qwen3-TTS-GGUF-74feb58-LICENSE.txt`。

- 授权人：GitHub 登录名 `HaujetZhao`（仓库 owner）。
- 授权形式：历史状态（2026-09-16）：issue 评论形式的非正式授权说明；没有许可证正文，也没有担保与责任条款。当前状态（2026-09-19 起）：仓库根目录已有作者本人的独立 MIT 许可证文件（提交 `74feb581`，见第 6 节），issue 授权继续保留。
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

原解读边界多数已由 MIT 消解（MIT 明文授予 use / copy / modify / merge / publish / distribute / sublicense / sell）；以下三条仍然成立：

1. 这是 issue 评论形式的非正式授权，**不是许可证文件**，没有担保与责任条款。
2. MIT 加入时间晚于我们固定的提交 `dc8950d7…`；对该提交的覆盖同时依据 issue #31 中不限版本的表述（“all the things I have written”），两条依据并存。
3. 根目录 MIT 仅用于上游作者有权授权的原创部分，不能改变仓库内 vendored 第三方组件各自的许可证（Qwen3-TTS、llama.cpp/ggml 等）；这些组件继续按各自许可证单独核算。我方 2026-09-17 的请求原文亦已声明会继续单独遵守这些组件各自的许可证。

## 5. 复核方法（只读）

```bash
gh api repos/HaujetZhao/Qwen3-TTS-GGUF/issues/31
gh api "repos/HaujetZhao/Qwen3-TTS-GGUF/issues/31/comments?per_page=100"
```

**历史状态（2026-09-17，两次只读检查一致）：** 仓库 `license` 字段为 `null`；默认分支根目录无 `LICENSE*` / `COPYING*` / `NOTICE*` 文件；上述回复未被编辑。

**当前状态（2026-09-19 复核）：** 仓库 `license` 字段为 `mit`；根目录存在 `LICENSE`（提交 `74feb581bc8c`，2026-09-19T00:59:52Z 加入，1067 B，blob `459ae02f40951e8c9191fdf3ec4afee72eccf9a7`）；OWNER 首条授权回复仍未被编辑（`created_at == updated_at`）；issue #31 现为 closed，共 4 条评论。上述变化已于 2026-09-19 发生，本记录按其更新（见第 6 节）。

状态注记：本项目已于 2026-09-17 在该 issue 中请求作者补充仓库根目录许可证文件；2026-09-19 作者回复「已添加。」并关闭 issue，同日落地独立 MIT 文件（提交 `74feb581`）。本记录的授权依据是上表 OWNER 回复本身，不依赖该请求的结果。

## 6. 上游仓库根目录 MIT（2026-09-19）

| 项 | 值 |
|---|---|
| 提交 | `74feb581bc8c`（「Add MIT License」），2026-09-19T00:59:52Z，作者 owner（`HaujetZhao`） |
| 变更范围 | 只动 `LICENSE` 一个文件（+21/−0） |
| 文件 | `LICENSE`，1067 B；blob `459ae02f40951e8c9191fdf3ec4afee72eccf9a7`；sha256 `65959dcac5c2748705a2c38159797ab79193eb657bf2395a5be9b107362e1058` |
| 收录 | 同目录 `Qwen3-TTS-GGUF-74feb58-LICENSE.txt`，按上游固定 revision 原样落盘（LF、无 BOM，未作任何转换） |
| 核验 | 与 GitHub 规范 MIT 模板（`gh api licenses/mit`）替换 `[year]`→2026、`[fullname]`→HaujetZhao 后逐行相同 |
| 关闭动作 | 作者在同日回复「已添加。」（评论 id `5738069275`，未被编辑）并关闭 issue #31 |

### 时间线（UTC）

| 时间 | 事件 |
|---|---|
| 2026-09-16T08:20:52Z | OWNER 首次公开授权：“Please feel free to use all the things I have written without any restrictions.”（未被编辑） |
| 2026-09-17T06:31:14Z | 我方请求补 LICENSE，原文点名「包括 issue 中提到的 `dc8950d7…`」，并声明「我们会继续单独遵守 Qwen3-TTS、llama.cpp/ggml 等第三方组件各自的许可证」 |
| 2026-09-19T00:57:58Z | 我方催更（`:)`） |
| 2026-09-19T00:59:52Z | OWNER 提交 `74feb581bc8c`「Add MIT License」，只动 `LICENSE` 一个文件（+21/−0） |
| 2026-09-19T01:01:13Z | OWNER 回复「已添加。」（评论 id `5738069275`，未被编辑） |
| 之后 | issue #31 已 closed |

范围排除由记录自身承载：我方 2026-09-17 的请求原文已声明会继续单独遵守 Qwen3-TTS、llama.cpp/ggml 等第三方组件各自的许可证；根目录 MIT 仅覆盖上游作者有权授权的原创部分。
