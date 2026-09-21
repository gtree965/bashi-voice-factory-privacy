# Maintenance and triage / 维护与分诊

**English** | [中文](#维护与分诊)

This page describes how this project is maintained: who responds, how issues are triaged, how
decisions are recorded, and what happens to reports that fall outside the project's scope.

---

## Current state

This project is maintained by a **single maintainer**. There is no external maintainer, no
triage team, and **no external issue or pull-request history yet**. That is stated plainly
because it directly affects what you can expect: **do not expect large-project response times
here.**

## Triage

Issues are triaged **in batches**. Within a batch, **security and blocking problems (the app
cannot start, data loss, a broken release artifact) are looked at first**; feature requests and
documentation issues come after.

We **do not promise response times, fix times, or a triage frequency** — with one maintainer,
promising a schedule would not be honest.

## Severity

| Level | Criteria | Order |
|---|---|---|
| High | the privacy posture is broken (any outbound traffic or telemetry appears), the app cannot start, or data is corrupted | first |
| Medium | a feature is unusable but a workaround exists, or performance regresses noticeably | normal triage |
| Low | documentation, wording, experience details | handled together with related changes |

## How decisions are recorded

- Directional decisions go to [`../ROADMAP.md`](../ROADMAP.md).
- User-visible changes go to [`../CHANGELOG.md`](../CHANGELOG.md).
- Implementation details live in the commit history, split by single responsibility, with the
  reasoning in the commit body.

## What gets closed

An issue may be closed as **"out of scope"** when it conflicts with the project's stated
boundaries (see the "Not planned / deliberately out of scope" section of `ROADMAP.md`) — for
example: telemetry of any kind, cloud fallback, or a change that would break the
privacy-first/local-only design. Closing is not a judgement on the reporter; it means the
request does not fit the project's boundaries.

## Release cadence

Patches are released **when real defects require them**; there is **no fixed release schedule**.

## Suggesting a roadmap change

Use the entry point documented in [`../ROADMAP.md`](../ROADMAP.md) under
"How to suggest a roadmap change" — it lists the public issue tracker and a private channel.
**Do not invent a new channel**; route suggestions through the ones that already exist.

---

# 维护与分诊

[English](#maintenance-and-triage) | **中文**

本页说明本项目如何被维护：谁响应、如何分诊、决策记录在哪里，以及超出项目边界的报告会怎样处理。

---

## 现状

本项目由**单一维护者**维护。没有外部维护者、没有分诊团队、也**尚无外部 Issue / PR 处理历史**。
之所以直说，是因为它直接决定你能期待什么：**不要按大项目的响应速度来预期这里。**

## 分诊

Issue **集中分诊**。同一批里，**安全与阻断类问题（应用无法启动、数据损坏、发布产物损坏）优先看**；
功能建议与文档类问题随后。

我们**不承诺响应时限、修复时限，也不承诺分诊频率**——只有一位维护者，承诺时间表是不诚实的。

## 严重度

| 级别 | 判据 | 处理次序 |
|---|---|---|
| 高 | 隐私承诺被破坏（出现任何外发/遥测）、无法启动、数据损坏 | 先处理 |
| 中 | 功能不可用但有替代路径、性能明显回退 | 常规分诊 |
| 低 | 文档、措辞、体验细节 | 与相关变更合并处理 |

## 决策如何被记录

- 方向性决定进 [`../ROADMAP.md`](../ROADMAP.md)。
- 用户可见变更进 [`../CHANGELOG.md`](../CHANGELOG.md)。
- 具体实现进提交历史：按单一职责拆分，取舍写在提交正文里。

## 什么情况下会被关闭

当请求与项目已声明的边界冲突时（见 `ROADMAP.md` 的「明确不做」一节），会被以「超出范围」关闭——
例如：任何形式的遥测、云端回退、或会破坏「隐私优先 / 纯本地」设计的改动。
关闭不是对报告人的评价，而是说明该请求不符合项目边界。

## 发布节奏

补丁**按实际缺陷需要发布**；**没有固定发布周期**。

## 如何提议路线图变更

用 [`../ROADMAP.md`](../ROADMAP.md) 里「How to suggest a roadmap change」一节给出的入口——
那里列着公开 Issue 跟踪器与私密渠道。**不要另造渠道**；请走已经存在的那些。
