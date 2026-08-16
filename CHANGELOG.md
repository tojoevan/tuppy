# CHANGELOG

## 设计阶段（2026-08）

- 架构设计 v1.0 → v1.1（简化重构：v0.1 极简循环 + 分阶段路线图）
- 终端从微信小程序改为自托管 web（小程序审核耗时，推迟）
- 命名：Tuppy（英文宠物名，无含义，GitHub 重名仅 16）
- 剧本 day-script.md：第一人称 voice + 早晚班节律
- v0.1-design.md：11 条设计洞全部定案，构建唯一参照
- 文档库 8 件套定稿

## v0.1（运行中，判据开始 2026-08-16）

**状态**：部署完成，14 天判据运行中（docs/status.md 跟踪）。手机已验证推送 + 点击跳转。

**推送**（v0.2-lite，2026-08-16）：自建 ntfy v2.27.0（VPS 127.0.0.1:2586，auth 单用户，iOS 走 ntfy.sh APNs 中转）。班后有话说才推，无事闭嘴。PushDeer 弃用（app 停在 2022，半维护）。通知带 Click 跳转：早班跳提议页，晚班跳待办页。周日晚班加周报心跳（存活证明）。

**鉴权替换**（2026-08-16）：Basic Auth 弃用（PWA standalone 弹窗缺陷、无登出）。换 Flask 登录页 + session cookie（30 天）。`/static/` 免鉴权。密码 `.env` TUPPY_PASSWORD。app 启动自读 .env（systemd 环境注入不可靠）。

**条目编辑/删除 + ICS 验证 + PWA**（2026-08-16）：录入表格渲染 ended_at/note（此前存了不显示）；编辑复用表单，删除带确认；ICS 导入端到端测试（定时+全天+冲突联动）；manifest + 图标。

**规则生态**（2026-08-16）：
- 独立仓库 tuppy-rules：格式规范 + rules.json（15 条）+ 数据源地图
- Tuppy 规则页 /rules：浏览 + 导出/导入（同域+分类+模板跳过，非法拒绝）
- seed.sql 改为生成物（scripts/sync_rules.py），规则单一事实源 = tuppy-rules
- 缺测冷启动修复：从首条数据录入日起算，历史导入不追溯

**部署体验**（2026-08-16）：页面"更新"按钮（trigger 文件 + root cron 每分钟捡信，零权限扩张）；版本号 v0.1.<hash> 在 header；deploy 脚本 fetch 12 秒超时防卡死；健康检查打 /login。

**修复**：导入去重（CSV '' vs NULL、TEXT vs REAL 类型失配）；gap 文案歧义（人称放括号）；首页空态重复问候；移动端表格溢出。

**代码初版**：

- schema.sql：六主表 + rule_log + import_staging（seed 四规则：缺测血压/冲突日程/突变电费/到期物品）
- engine.py：四模板解释器 + 两班 + 限额3 + 影子四类 + 反馈降权 + 健康检查 + 备份轮转
- app.py：五页 + 导入（CSV/ICS，预览确认 + 五元组去重）+ Tuppy voice flash
- tests：18 用例全过（四模板边界 + 限额 + 降权）

**部署**（2026-08-15）：VPS 150.158.120.205 宝塔环境，/www/wwwroot/tuppy.oahubs.com
- systemd User=www + www crontab 两班（06:30 / 22:00）
- 端到端验证过：录数据 → 早班 → 提议上首页
- 反代：宝塔面板用户侧配置

**待办**：跑 14 天判据（设计文档 §14），接受率 ≥30% 才算 v0.1 完成
