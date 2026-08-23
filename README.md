# Tuppy

你的夜间守家小东西。一个归你所有的 agent，替你看守你的世界，只报和你有关的事，判断权留给你。

> Every captain sleeps. Tuppy keeps the watch.

## 是什么

Tuppy 不是聊天机器人，不是 todo 工具。它是一天两班的值守者：

- **早班**：扫你录的数据（账本、日程、健康），发现值得说的事，说 2-3 条
- **晚班**：消化你白天的反馈，写"它今天看到什么"的影子报告

你只做三个动作：**选择**（点按钮表态）、**输入**（喂数据）、**查看**（审计它干了什么）。

## 核心原则

- **它主动，你判断**：Tuppy 只提议，不决定。每个动作必须你点头
- **宁可少说，不可错说**：每天打扰有预算，超了闭嘴，攒进摘要
- **可审计**：一切决策留痕。你能看它挡了什么、为什么、按什么规则
- **可解雇**：一键静默、一键导出全部数据。能被解雇才敢被信任
- **归你所有**：SQLite 是全部数据，模型能换，agent 能杀。收用户钱，不收平台钱

## 当前状态

v0.1 已闭环；v0.2 功能完成、进入 14 天判据观察期（2026-08-16 → 08-30）；v0.3 ESP32 语音终端主目标已通，固件改造待烧录验证。详见 [docs/status.md](docs/status.md)。

| 文档 | 内容 |
|---|---|
| [docs/v0.2-design.md](docs/v0.2-design.md) | v0.2 设计（**进行中，构建参照**） |
| [docs/v0.1-design.md](docs/v0.1-design.md) | v0.1 完整设计（已固化，tag v0.1） |
| [docs/day-script.md](docs/day-script.md) | 一天剧本（voice 参照） |
| [docs/architecture.md](docs/architecture.md) | 愿景层（冻结） |
| [docs/status.md](docs/status.md) | **项目当前状态**（部署、URL、判据进度） |
| [docs/testing.md](docs/testing.md) | 测试策略 |
| [docs/release.md](docs/release.md) | 发布与部署 |
| [docs/deploy-workflow.md](docs/deploy-workflow.md) | **部署运作流程 + 未白×joevan 配合方式**（速查） |
| [docs/security.md](docs/security.md) | 安全模型 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |

## v0.1 范围

- 一个用户：你
- 输入：手动录入 + 导入（ICS/CSV）
- 判断：纯规则引擎（模板 + 参数实例），无模型调用
- 输出：提议页 + 待办 + 影子报告 + 周报
- 技术栈：Python + Flask + SQLite + cron

## 规则集

`seed.sql` 是**生成物**，由 `scripts/sync_rules.py` 从 [tuppy-rules](https://github.com/tojoevan/tuppy-rules) 仓库的 `rules.json` 生成。

改规则流程：改 tuppy-rules → `python scripts/sync_rules.py` → 提交 Tuppy。

## 路线图

```
v0.1  值守（web 页，你来看）        ✅ 闭环
v0.2  会叫你（推送 + 打扰预算器）     ✅ 功能完成，观察期
v0.3  ESP32 一体机（桌宠+看板+语音录入）← 语音终端✅ / 固件改造待烧录
v0.4  安卓通知源 + 隐私牌
v0.5  静音牌/多成员/小程序
```

## 许可证

MIT
