# Tuppy 项目状态

> 最后更新：2026-08-16

## 当前阶段

**v0.1 部署完成，14 天判据运行中**（开始：2026-08-16，结束：2026-08-30）

## 已落地

| 组件 | 状态 | 位置 |
|---|---|---|
| 规则引擎（四模板 + 15 规则） | ✅ | engine.py + rules 表 |
| Web 终端（六页） | ✅ | app.py + templates/ |
| 条目编辑/删除 | ✅ | 录入页表格 |
| CSV/ICS 导入（去重） | ✅ | 端到端测试过 |
| Flask 登录页（替换 Basic Auth） | ✅ | /login，30 天 session |
| PWA | ✅ | manifest + 图标 |
| 规则页（浏览/导出/导入） | ✅ | /rules |
| 推送（自建 ntfy + 周报心跳） | ✅ | ntfy.oahubs.com |
| 页面更新按钮 | ✅ | trigger 文件 + root cron |
| 自动部署 | ✅ | cron 5 分钟 + push 后手动触发 |
| 测试 | ✅ 39 用例全过 | tests/ |

## 关键 URL

- Web：https://tuppy.oahubs.com（Flask 登录页）
- ntfy：https://ntfy.oahubs.com（topic `tuppy`，用户 `tuppy`）
- 仓库：https://github.com/tojoevan/tuppy
- 规则集：https://github.com/tojoevan/tuppy-rules

## 运行机制

```
cron 06:30 早班 → 扫规则 → 提议 ≤3 条 → 有提议则推手机（点击跳提议页）
cron 22:00 晚班 → 反馈降权 + 影子报告 + 备份 → 有待办则推手机
                  周日加周报心跳（存活证明）
```

推送链路：Tuppy POST → ntfy（127.0.0.1:2586）→ 手机 app。无事不推。iOS 唤醒走 ntfy.sh 中转（仅信号）。

## 规则生态

- 规则单一事实源：tuppy-rules 仓库 `rules.json`（格式标准 + 15 条规则 + 数据源地图）
- seed.sql 是生成物：`scripts/sync_rules.py` 从 rules.json 生成，不手改
- 生产库规则更新走规则页导入（seed 只在建库时播种）

## 14 天判据（v0.1 完成标准，见 v0.1-design.md §14）

- [ ] 录入 ≥30 天跨度数据（含导入）
- [ ] 提议接受率 ≥30%
- [ ] 影子报告打开 ≥5 次
- [ ] 页面访问不停用（间隔 >3 天算停用）

判据结束日：2026-08-30

## 已知事项

- VPS 连 GitHub 不稳：fetch 12 秒超时跳过，scp fallback 可用；deploy 脚本已加固
- 生产库已录 1 条：信用卡还款 8/23（8/21 早班将出第一条真提议）
- 种子规则 15 条（含缴费/车辆/宠物/证件/健康域），没数据的安静沉默
- ntfy 密码在 `/etc/ntfy/server.yml`（hash）+ `.env`（明文）两处，改密码需双同步 + 手机 app
- schema.sql 变更不会自动迁移，需手动处理
- 部署健康检查打 /login（根路径 302 是登录拦截，非故障）

## 下一步候选（由 14 天使用摩擦决定，不由路线图）

- 加域/加模板：录了什么新数据、缺什么发现能力
- 待办页强化：截止时间、优先级
- v0.2 完整推送：打扰预算器、分级通道
- 规则 provenance：作者/使用数/命中率（等判据数据）
- 数据源地图扩充：贡献更多"产品→导出方式"线索
