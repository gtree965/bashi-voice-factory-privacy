# Contributing to Bashi Voice Factory Privacy Edition

**English** | [中文](#为巴适声工厂--隐私版贡献代码)

Thanks for considering a contribution. This guide is deliberately blunt about what works from a
source checkout today: the source-bootstrap path is only partially covered, and the sections
below state exactly what you can run yourself, what needs extra inputs, and what the maintainer
covers.

---

## 1. Start here

- Bug reports and feature requests go to **GitHub Issues**:
  <https://github.com/gtree965/bashi-voice-factory-privacy/issues>.
- Small, single-responsibility pull requests are welcome.
- Direction and scope live in [`ROADMAP.md`](ROADMAP.md); user-visible changes are recorded in
  [`CHANGELOG.md`](CHANGELOG.md).

**Where this repository stands today**

- This is a **single-maintainer project**. There is no external triage team and no external
  issue or pull-request history yet, so please do not expect large-project response times.
- The source contribution surface is **limited**: a fresh clone can run a meaningful test
  subset, but cannot start the application, build the portable package, or run the release
  gates without extra inputs that are not distributed with the source. This is tracked as the
  **source bootstrap known limitation** in [`ROADMAP.md`](ROADMAP.md).

## 2. What you can run today

### 2.1 The zero-dependency test subset

**A fresh clone plus a virtual environment that has nothing but `pip` can run nine test modules
that need no third-party package.** Verified commands (Windows PowerShell):

```powershell
git clone https://github.com/gtree965/bashi-voice-factory-privacy.git
Set-Location bashi-voice-factory-privacy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip list        # must show pip only
.\.venv\Scripts\python.exe -m unittest `
  tests.test_backend_probe `
  tests.test_check_pdf_links `
  tests.test_download_utils `
  tests.test_lan_prompt `
  tests.test_license_docs_gate `
  tests.test_portable_dependency_install `
  tests.test_pre_commit_guard `
  tests.test_streaming_retry_boundaries `
  tests.test_voice_catalog
```

Measured on 2026-09-21 (Windows, Python 3.12.10, pip 25.0.1): `Ran 144 tests`, `OK (skipped=5)`,
exit code 0. Timing is a **single measurement on one machine** (about 54 s here), not a promise.

⚠️ Do **not** substitute `python -m unittest discover -s tests`. The remaining test modules
import third-party packages, so discovery ends red even when your change is fine (measured:
`Ran 160 tests`, `FAILED (errors=14, skipped=7)`, exit code 1).

### 2.2 Two general hygiene checks

| Command | Purpose | Measured |
|---|---|---|
| `git diff --check` | whitespace and conflict-marker check | exit 0, no output |
| `node --check static/js/app.js` | front-end syntax check (needs Node.js) | exit 0, no output |

### 2.3 What you cannot run yet

| Check | Needs | Status |
|---|---|---|
| starting the app from source | embedded Python runtime, model weights, and one runtime directory outside the repository | not possible from a clone |
| building the portable ZIP | the same inputs | maintainer-run |
| release gates (PDF link gate, license pack gate, asset checks) | packaged artifacts | maintainer-run |

## 3. Development environment (optional, and heavy)

This installs the real runtime dependencies, **including PyTorch** — it is **not** a lightweight
development environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

[`requirements-dev.txt`](requirements-dev.txt) is pinned: it pulls in `requirements.txt` and adds
`pytest==9.1.1`.

Measured cost on 2026-09-21 (single machine, single measurement — not a general promise):
**about 410 MB of downloads**, **75 `Downloading` records** reported by pip, **72 installed
distributions** afterwards (`pip freeze`); the install took about 102 s, and the suite then
reports `255 passed, 7 skipped, 203 subtests passed` in about 62 s, exit code 0.

The first two numbers are pip's own display, and you can reproduce them: 410 MB is the sum of
the rounded sizes pip prints (not exact transferred bytes), and 75 is the count of `Downloading`
lines — not the package count. Transitive dependencies get re-downloaded while pip backtracks
(SciPy alone produced three records here), which is why 75 download records end up as only
72 installed distributions.

To isolate your own change, run one file (or one test) instead:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_text_chunking.py -q
```

## 4. Local commit guard: please do not enable it

`scripts/git-hooks/` contains three Git hooks (`pre-commit`, `commit-msg`, `pre-push`) plus a
guard program. They serve the **maintainer's release flow**: they block ignored paths, local
sensitive terms, and machine/tooling residue before a commit or a push.

**External contributors should not enable them. There is one practical reason:**

- The guard requires a **local term list** (`.git/info/bashi-sensitive-terms.txt`) that is **not
  shipped with the repository**. The maintainer keeps it locally, and the guard fails closed
  when it is absent — the first commit is blocked with:
  ```
  [commit guard] BLOCKED: Local term list is missing, unreadable or empty.
  ```
  You cannot obtain the maintainer's list, and you should not invent one.

The identity check inside the guard — the one that compares commits and annotated tags with the
maintainer's identity — is **scoped to official repository targets** (this project's GitHub and
Gitee repositories); a push that resolves to your own fork is **not** held to that identity.
That does **not** change the conclusion below: the missing local term list still blocks your
commit, so the guard stays unusable for external contributors.

Also note that `core.hooksPath` switches on **all three hooks at once**; there is no
"pre-commit only" setting.

**Conclusion:** the guard is the maintainer's release discipline, not a contributor gate.
**Your pull request does not need to pass it.**

For completeness, two bypasses exist (using them is not recommended): `git commit --no-verify`
and `git push --no-verify` skip the hooks; message lines starting with `#` are not checked at
commit time, but the push stage re-reads messages verbatim and does check them.

## 5. Commits: one responsibility each

We split commits by **single responsibility**: one commit does one reviewable thing, and the
reasoning goes in the commit body where it is not obvious. The history shows this practice
(`a751dcf`, `057f821`, `5d614c7` are small single-purpose changes); `ROADMAP.md` and
`CHANGELOG.md` record how each change is logged.

A good-enough format:

```
<scope>: <what changed>

<why; non-obvious trade-offs>
```

⚠️ There is no written rule yet on how to split. The paragraph above describes existing
practice; it does not claim a historical rule.

## 6. Declaring what you could not run

Some checks cannot run from a clone (see §2.3). In your pull request, say in one sentence what
you did not run and how you verified your change instead. For example:

> I could not build the portable ZIP, and I could not run one real synthesis or transcription with
> the actual model weights: both need inputs that are not distributed with the source (see §2.3).
> I covered my change with `.\.venv\Scripts\python.exe -m pytest tests -q` and reviewed the
> affected code paths by hand.

A statement like that does not make your pull request harder to accept — it tells the maintainer
what to re-run.

## 7. What the maintainer covers

The maintainer runs the checks a clone cannot: packaging, the PDF link gate, the license pack
gate, asset checks, real startup acceptance with models, and the integration tests that need
components outside the repository. **You do not need to assemble any of those conditions to open
a pull request.**

## 8. Licenses and third-party materials

Project code is MIT ([`LICENSE`](LICENSE)). Bundled models and third-party components keep their
own licenses: see [`THIRD_PARTY.md`](THIRD_PARTY.md), the gaps list in
[`THIRD_PARTY_GAPS.md`](THIRD_PARTY_GAPS.md), and the license texts under
[`licenses/`](licenses/). If your change adds or replaces a third-party component, say so in the
pull request; the build-time license gate is maintainer-run.

---

# 为巴适声工厂 · 隐私版贡献代码

[English](#contributing-to-bashi-voice-factory-privacy-edition) | **中文**

感谢你考虑为本项目做贡献。本文对「源码路径今天到底能做什么」如实说明：源码引导路径目前只覆盖了一部分，
下面各节写清了你**自己**能跑什么、哪些检查需要额外输入、以及维护者会补做哪些验收。

---

## 1. 从这里开始

- Bug 报告与功能建议请提到 **GitHub Issues**：
  <https://github.com/gtree965/bashi-voice-factory-privacy/issues>。
- 欢迎小而单一职责的 Pull Request。
- 方向与范围见 [`ROADMAP.md`](ROADMAP.md)；用户可见变更记录在
  [`CHANGELOG.md`](CHANGELOG.md)。

**仓库现状**

- 本项目目前由**单一维护者**主导，没有外部分诊团队，也**尚无外部 Issue / PR 处理历史**，
  请不要按大项目的响应速度来预期。
- 源码贡献面是**有限的**：全新克隆可以跑一个有意义、且已验证为绿的测试子集，
  但在没有额外输入（不随源码分发）的情况下，**无法启动应用、无法打包、无法跑发布期门禁**。
  这一点记录在 [`ROADMAP.md`](ROADMAP.md) 的 **source bootstrap known limitation** 条目里。

## 2. 你现在就能跑

### 2.1 零第三方依赖的测试子集

**全新克隆 + 一个只有 `pip` 的虚拟环境，就能跑九个不依赖任何第三方包的测试模块。**
已验证命令（Windows PowerShell）：

```powershell
git clone https://github.com/gtree965/bashi-voice-factory-privacy.git
Set-Location bashi-voice-factory-privacy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip list        # 应只有 pip
.\.venv\Scripts\python.exe -m unittest `
  tests.test_backend_probe `
  tests.test_check_pdf_links `
  tests.test_download_utils `
  tests.test_lan_prompt `
  tests.test_license_docs_gate `
  tests.test_portable_dependency_install `
  tests.test_pre_commit_guard `
  tests.test_streaming_retry_boundaries `
  tests.test_voice_catalog
```

2026-09-21 实测（Windows、Python 3.12.10、pip 25.0.1）：`Ran 144 tests`、`OK (skipped=5)`、
退出码 0。耗时是**本机单次测量**（约 54 秒），不是通用承诺。

⚠️ **不要**用 `python -m unittest discover -s tests` 代替上面这条命令。其余测试模块会导入
第三方包，所以即使你的改动没问题，整轮也会是红的（实测：`Ran 160 tests`、
`FAILED (errors=14, skipped=7)`、退出码 1）。

### 2.2 两条通用卫生检查

| 命令 | 用途 | 实测 |
|---|---|---|
| `git diff --check` | 空白与冲突标记检查 | exit 0，无输出 |
| `node --check static/js/app.js` | 前端语法检查（需本机有 Node.js） | exit 0，无输出 |

### 2.3 你现在还跑不了什么

| 检查 | 需要什么 | 状态 |
|---|---|---|
| 从源码启动应用 | 嵌入式 Python 运行时、模型权重、以及仓库之外的一个运行时目录 | 克隆里做不到 |
| 打包便携 ZIP | 同上 | 维护者执行 |
| 发布期门禁（PDF 链接门禁、许可落包门禁、资产核对） | 构建产物 | 维护者执行 |

## 3. 开发环境（可选，且很重）

这会装上真实的运行时依赖，**包括 PyTorch**——**不是**轻量开发环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

[`requirements-dev.txt`](requirements-dev.txt) 是固定版本的：它拉入 `requirements.txt`，
再加 `pytest==9.1.1`。

2026-09-21 实测代价（**本机单次测量**，不是通用承诺）：**下载约 410 MB**、pip 报出
**75 条 `Downloading` 记录**、最终 **72 个已安装发行包**（`pip freeze`）；安装约 102 秒，
随后整套测试输出 `255 passed, 7 skipped, 203 subtests passed`，约 62 秒，退出码 0。

前两个数字都是 pip 自己的显示值，你可以自行复核：410 MB 是 pip 打印的**四舍五入大小求和**
（不是精确传输字节），75 是 `Downloading` 行数而**不是包数**——传递依赖会在 pip 回溯时被
重复下载（这里仅 SciPy 就占了三条记录），所以 75 条下载记录最终只装出 72 个发行包。

只隔离自己的改动时，跑单个文件（或单个用例）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_text_chunking.py -q
```

## 4. 本地提交守卫：请不要启用它

`scripts/git-hooks/` 里有三个 Git 钩子（`pre-commit`、`commit-msg`、`pre-push`）和一个守卫程序。
它们服务**维护者的发布流程**：在提交与推送前挡住被忽略的路径、本地敏感词、以及机器/工具残留痕迹。

**外部贡献者不要启用它们。有效理由只有一条：**

- 守卫需要一个**本地词表**（`.git/info/bashi-sensitive-terms.txt`），而这个词表**不随仓库提供**。
  它由维护者在本地维护；缺失时守卫**直接 fail closed**，第一次提交就会被挡住：
  ```
  [commit guard] BLOCKED: Local term list is missing, unreadable or empty.
  ```
  你拿不到维护者的词表，也**不应该**为了它去自造一份。

守卫里的身份校验（把提交与附注标签和维护者身份比对）只作用于**官方仓库目标**（本项目的
GitHub 与 Gitee 仓库）；已解析为你自己 fork 的推送**不会**被这个身份卡住。但**这并不改变
下面的结论**：本地词表缺失仍会挡住你的提交，所以守卫对外部贡献者依旧不可用。

另外注意：`core.hooksPath` 是**一开全开**——三个钩子同时生效，没有「只启用 pre-commit」这种开法。

**结论**：守卫是**维护者的发布纪律**，不是贡献者门槛；**你的 PR 不需要过它**。

顺带如实告知两个绕过口（**不建议使用**）：`git commit --no-verify` 与 `git push --no-verify`
会跳过钩子；消息里以 `#` 开头的行在提交环节不会被检查，但推送环节会逐字重读并检查。

## 5. 提交信息与拆分

我们按**单一职责**拆分提交：一个提交只做一件可被独立审查的事，理由写在提交正文里（不显然时）。
仓库历史里能看到这种实践（`a751dcf`、`057f821`、`5d614c7` 都是小范围单一职责改动）；
`ROADMAP.md` 与 `CHANGELOG.md` 记录了每项变更如何被登记。

一个够用的格式：

```
<范围>: <做了什么>

<为什么这样做；不显然的取舍>
```

⚠️ 目前「为什么这样拆」**还没有成文规则**——上面这段只是把既有实践写下来，不宣称它是历史规则。

## 6. 在 PR 里如实声明未跑项

有些检查在克隆里跑不了（见 §2.3）。请在 PR 描述里用一句话说明你**没跑什么**、以及你用什么方式
验证了自己的改动。例如：

> 我没能构建便携 ZIP，也没能用真实模型权重跑一次合成或转写：这两项需要的输入都不随源码
> 分发（见 §2.3）。我改为用 `.\.venv\Scripts\python.exe -m pytest tests -q` 覆盖自己的改动，
> 并手工复核了受影响的代码路径。

这样的声明**不会**让你的 PR 更难被接受；相反，它让维护者知道该补跑什么。

## 7. 维护者会补做哪些验收

克隆里跑不了的检查由维护者执行：打包、PDF 链接门禁、许可落包门禁、资产核对、带模型的真实启动验收，
以及需要仓库外组件的集成测试。**你不需要为了提 PR 去凑齐这些条件。**

## 8. 许可与第三方材料

项目代码为 MIT（[`LICENSE`](LICENSE)）。随包分发的模型与第三方组件遵循各自许可：
见 [`THIRD_PARTY.md`](THIRD_PARTY.md)、缺口清单 [`THIRD_PARTY_GAPS.md`](THIRD_PARTY_GAPS.md)，
以及 [`licenses/`](licenses/) 下的许可证原文。若你的改动新增或替换了第三方组件，请在 PR 里说明；
构建期许可门禁由维护者执行。
