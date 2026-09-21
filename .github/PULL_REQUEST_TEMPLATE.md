<!-- 每一节先英文后中文。/ English first, Chinese below each heading. -->

## 这个 PR 做了什么 / What this PR does

<!--
一句话说清「改了什么」与「为什么」。
One sentence: what changed, and why.
-->

## 你跑过的检查（勾选真正跑过的）/ Checks you ran (tick what you actually ran)

- [ ] `git diff --check`
- [ ] `node --check static/js/app.js`（改了前端 JS 才需要；本机需有 Node.js / only if you changed front-end JS; needs Node.js）
- [ ] `.\.venv\Scripts\python.exe -m pytest tests -q`（开发环境；应为零 failed、零 errors / development environment; zero failed, zero errors）
- [ ] 零依赖九模块命令（没有搭开发环境时，见 [`CONTRIBUTING.md`](https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/CONTRIBUTING.md) §2.1 / the zero-dependency nine-module command if you did not set up the dev environment）
- [ ] 其他（请写明命令与结果）/ Other (write the command and the result):

## 你没能跑的检查（请如实填写，不影响是否接受）/ Checks you could not run (honest answers welcome)

<!--
本项目当前无法从源码完整启动：嵌入式 Python、模型权重目录、以及一个仓库外的运行时目录都不随源码分发。
因此打包、模型加载、真实合成/转写、发布期门禁都不该由你证明。
请写：哪条没跑、为什么、你用什么替代方式验证了自己的改动。
A clone cannot start the app, build the package, or run the release gates — those are not yours
to prove. Say which check you skipped, why, and how you verified your change instead.
-->

## 与既定方向的关系 / Relation to the roadmap


- 与 [`ROADMAP.md`](https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/ROADMAP.md) 的一致性（请自行填写）/ consistency with ROADMAP.md (please fill in):
- 若改动用户可见行为，[`CHANGELOG.md`](https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/CHANGELOG.md) 是否需要补一行（请自行填写）/ if it changes user-visible behaviour, whether CHANGELOG.md needs a line (please fill in):
