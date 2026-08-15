# Tuppy 项目状态

> 最后更新：2026-08-16

## 当前阶段

**v0.1 部署完成，14 天判据运行中**（开始：2026-08-16）

## 已落地

| 组件 | 状态 | 位置 |
|---|---|---|
| 规则引擎（四模板） | ✅ | engine.py |
| Web 终端（五页） | ✅ | app.py + templates/ |
| 测试 | ✅ 18 用例全过 | tests/ |
| VPS 部署 | ✅ | 150.158.120.205，宝塔环境 |
| Basic Auth | ✅ 用户已在宝塔面板开启 | tuppy.oahubs.com |
| 推送（自建 ntfy） | ✅ 手机已验证跳转 | ntfy.oahubs.com |
| 自动部署 | ✅ cron 5 分钟轮询 | /usr/local/bin/tuppy-deploy.sh |

## 关键 URL

- Web：https://tuppy.oahubs.com（Basic Auth）
- ntfy：https://ntfy.oahubs.com（topic `tuppy`，用户 `tuppy`）
- 仓库：https://github.com/tojoevan/tuppy

## 运行机制

```
cron 06:30 早班 → 扫规则 → 提议 ≤3 条 → 有提议则推手机（点击跳提议页）
cron 22:00 晚班 → 反馈降权 + 影子报告 + 备份 → 有待办则推手机（点击跳待办页）
```

推送链路：Tuppy POST → ntfy（127.0.0.1:2586）→ 手机 app。无事不推。iOS 唤醒走 ntfy.sh 中转（仅信号，不含内容）。

## 14 天判据（v0.1 完成标准，见 v0.1-design.md §14）

- [ ] 录入 ≥30 天跨度数据（含导入）
- [ ] 提议接受率 ≥30%
- [ ] 影子报告打开 ≥5 次
- [ ] 页面访问不停用（间隔 >3 天算停用）

判据结束日：2026-08-30

## 已知事项

- VPS 连 GitHub 不稳（curl 56/443 超时）：scp fallback 可救急，auto-deploy 网络恢复后自动收敛
- ntfy 密码在 `/etc/ntfy/server.yml`（hash）+ `.env`（明文）两处，改密码需双同步 + 手机 app
- schema.sql 变更不会自动迁移，需手动处理
- 测试数据已清空（2026-08-16），DB 为真实数据起点

## 下一步候选（由 14 天使用摩擦决定，不由路线图）

- 加域/加模板：录了什么新数据、缺什么发现能力
- 待办页强化：截止时间、优先级
- v0.2 完整推送：打扰预算器、分级通道
- 影子报告优化：第一周后改周报附 top5 的节奏是否合适
