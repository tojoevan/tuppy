# 案例：Tuppy v0.3 固件功能验证报告

> 日期：2026-08-16
> 设备：微雪 ESP32-S3 2.06" 触控 AMOLED（410×502）
> 固件：xiaozhi-esp32 2.0.5 + Tuppy 改造（git 记录可查）
> 结论：核心功能全部验证通过，MCP 语音闭环达标

## 1. 验证环境

- VPS：150.158.120.205（宝塔，mosquitto 1883/1884 + nginx 反代 /mqtt）
- 固件仓库：xiaozhi-esp32-2.0.5-amoled-2.06（本地 git，main 分支）
- Tuppy 后端：/www/wwwroot/tuppy.oahubs.com（Flask + SQLite + MCP stdio 桥）
- 链路：固件 wss://tuppy.oahubs.com/mqtt → nginx /mqtt → mosquitto 1884(ws) → 1883 → Tuppy

## 2. 验证结果总表

| # | 功能 | 结果 | 说明 |
|---|---|---|---|
| A1 | MQTT 连接 | ✅ | 固件连上 mosquitto（ESP32_f32CF0） |
| A2 | 心跳 | ✅ | 每 30s 发 tuppy/heartbeat |
| A3 | status 主屏显示 | ✅ | "Tuppy | N proposal | M todo" 常驻聊天区 |
| A4 | announce 主屏显示 | ✅ | "Tuppy: xxx" |
| B1 | 电源键短按 | ✅ | 屏显"电源键 快捷录入" + MQTT |
| B2 | 电源键双击 | ✅ | 屏显"电源键 看板切换" + MQTT |
| B3 | 电源键三击 | ✅ | 屏显"电源键 家庭广播(预留)" + MQTT |
| C3 | BOOT 双击 | ✅ | 屏显"BOOT键 静音牌" + MQTT（修复后） |
| C4 | BOOT 三击 | ✅ | 屏显"BOOT键 隐私牌" + MQTT（修复后） |
| D | 官方语音回归 | ✅ | 唤醒/对话正常，Tuppy 改动无破坏 |
| E | MCP 语音闭环 | ✅ | 录入/查询链路通，数据落库 source=voice |

## 3. 验证中发现并修复的问题

### 3.1 MQTT 502（nginx 反代）
- **现象**：https://tuppy.oahubs.com/mqtt 502，固件连不上
- **根因**：宝塔默认 `location ^~ /` 抢走 `location /mqtt`；且 mosquitto websocket 是 HTTP/1.1，curl HTTP/2 测试产生假 502
- **修复**：`location ^~ /mqtt` + `proxy_pass http://127.0.0.1:1884/`（剥离 /mqtt 路径）
- **详见**：[2026-08-16-mqtt-502-location-priority.md](2026-08-16-mqtt-502-location-priority.md)

### 3.2 Tuppy 状态屏显不可见
- **现象**：收到 tuppy/status 但屏幕无显示
- **根因**：`SetStatus` 写 status_label_ 会被 `UpdateStatusBar` 每 10s 覆盖成时间；`ShowNotification` 弹层 5s 消失
- **修复**：改用 `SetChatMessage("system", ...)` 显示到主屏聊天区，常驻可见

### 3.3 中央表情遮挡消息
- **现象**：Tuppy 消息显示时被 AI 表情图标挡住
- **根因**：官方 `SetChatMessage` 只对非 system 消息隐藏 emoji
- **修复**：板级 CustomLcdDisplay override SetChatMessage，先隐藏 emoji 再调基类

### 3.4 BOOT 键双击/三击不触发
- **现象**：BOOT 双击/三击无反应（首次触发后卡死）
- **根因**：Tuppy 用 Button 封装在 GPIO0 新建第二个实例，与官方 boot_button_ 冲突（gpio_isr_handler_add 同 GPIO 只保留一个 handler）
- **修复**：不新建实例，把双击/三击挂到官方 boot_button_，回调 TuppyLink::OnBootKey

### 3.5 心跳 uptime 格式
- **现象**：`{"uptime":ld}` 显示异常
- **根因**：esp-idf snprintf %lld 输出问题
- **修复**：int 转换 + %d

### 3.6 MCP 语音录入 ASR 误识
- **现象**：说"记一笔"→ title 落成"G比牛奶"
- **根因**：ASR 把"记一笔"听成"G比"（屏幕原文确认），非 LLM/Tuppy 侧
- **修复**：换触发词"帮我记一下"→ 识别完美（title=牛奶、日期 8/20 解析、category=食品）

## 4. MCP 语音闭环实测数据

| id | 触发词 | domain | title | happened_at | source |
|---|---|---|---|---|---|
| 7 | "记一笔" | 物品 | G比牛奶（ASR 误识） | 2026-08-16 | voice |
| 8 | "帮我记一下" | 物品 | 牛奶 ✅ | 2026-08-20 ✅ | voice |
| 6 | 自然说 | 健康 | 更新胰岛素针头 | 2026-08-16 | voice |

- **日期解析**：LLM 正确解析"8 月 20 号"→ 2026-08-20（"帮我记一下"时）
- **category 智能**：物品域下自动给"食品"

## 5. 固件 git 提交记录（改造全程）

```
c3a5683 fix: 心跳 uptime 格式（%lld 输出异常改 %d+int）
e7e76bc fix: BOOT 键手势挂到官方 boot_button_（消除 GPIO ISR 冲突）
584ff50 fix: Tuppy 消息显示时隐藏中央 AI 表情
62fdbdd feat: Tuppy 状态/播报显示到主屏聊天区（system 消息）
c5ee362 feat: MQTT 心跳 + ACK 确认通道
824d75e fix: tuppy/status 屏显用 ShowNotification 替代 SetStatus
fb0b66e fix: 电源键长按让回 PMIC 关机（移除 Tuppy 紧急全静音）
e710f65 feat: 电源键四手势（AXP2101 PEK）+ OnPowerKey 事件收口
eb15786 feat: 官方 xiaozhi-esp32 2.0.5 baseline + Tuppy 语音终端改造点
```

## 6. 验证工具沉淀

- **心跳**：固件每 30s 发 tuppy/heartbeat，VPS 持续收到 = 通道稳定（定位断线）
- **ACK**：固件收到 status/announce 回 tuppy/ack，VPS 确认固件真收到（区分"没收到"vs"收到没显示"）
- **VPS 耳朵**：mosquitto_sub -t 'tuppy/#' 监听全部 Tuppy topic，实时确认固件事件

## 7. 遗留与建议

1. 心跳 uptime 修复（c3a5683）已编译，**待下次刷机验证** `{"uptime":数字}`
2. "记一笔"触发词 ASR 识别差——**正式使用统一用"帮我记一下"**
3. 电源键长按 = PMIC 4s 硬件关机（Tuppy 不占用）
4. 后续可做：VPS 侧按键语义（double=停推一天、triple=断听）、announce TTS 播报
