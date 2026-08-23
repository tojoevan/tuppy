# Tuppy v0.3 固件烧录与验收 Checklist

> 用途：回工作室后烧录微雪 ESP32-S3 2.06" AMOLED 板，验证 v0.3 固件改造（MQTT + 屏显 + 按键）。
> 代码状态：阶段 0~3 **全部代码完成**，本 checklist 聚焦「烧录 + 真机验证」。
> 硬件：微雪 ESP32-S3 触控 AMOLED 2.06"（410×502 QSPI）+ 双麦 + 喇叭。
> 固件基线和源码：`xiaozhi-esp32-2.4.2`，板型 `boards/waveshare/esp32-s3-touch-amoled-2.06`。
>
> **验收状态（2026-08-23 晚）**：✅ **v0.3 硬件验收通过**——阶段 0 官方固件 + 语音录入主目标（MCP 双向，source='voice'）已真机跑通。阶段 1~3（MQTT 状态屏显 / announce 播报 / BOOT·电源键手势）属后续扩展愿景，本轮未做、不计入验收。

---

## 阶段 0：官方固件编译烧录验证（基线）

- [ ] ESP-IDF 环境就绪（`idf.py --version` 正常）
- [ ] 切到 `xiaozhi-esp32-2.4.2` 目录
- [ ] `idf.py set-target esp32s3`
- [ ] `idf.py menuconfig` → 选 board `waveshare/esp32-s3-touch-amoled-2.06`
- [ ] `idf.py build` 通过（无报错）
- [ ] USB 连板，`idf.py flash monitor` 烧录 + 看日志
- [ ] 板子开机、屏亮、能进官方语音对话（说一句话有回应）
- [ ] 阶段 0 通过标记：`✅ 官方固件编译烧录验证`

> 阶段 0 已在设计文档标 ✅，回工作室先复跑一遍确认环境没坏。

---

## 阶段 1：MQTT 通道 + VPS mosquitto + Tuppy 状态发布

> 固件侧：加独立 MQTT 客户端（与官方 WebSocket 并行）。
> VPS 侧：`shifts.py after_shift()` 已调用 `notify.mqtt_status()` 班后发布（代码 ✅）。

- [ ] VPS `mosquitto` 运行：`systemctl is-active mosquitto`（或 `mosquitto_pub -h 127.0.0.1 -t tuppy/test -m hi` 不报错）
- [ ] 固件烧录含 MQTT 客户端的版本，`idf.py flash monitor` 看启动日志无 MQTT 连接报错
- [ ] 手动触发班后状态：VPS 上 `sudo -u www .venv/bin/python shifts.py evening`（或等 22:00）
- [ ] 固件日志显示收到 `tuppy/status`：提议数 / 待办数 / 健康态
- [ ] 阶段 1 通过标记：屏显状态区出现提议数/待办数/健康灯

---

## 阶段 2：屏显状态区 + announce 弹层

> 代码 ✅（待烧录验证）。桌宠灯态 → AMOLED 屏状态区；看板 → 屏显 Tuppy 状态页。

- [ ] 屏显状态区渲染正常（状态色块 + 图标，非黑屏/错位）
- [ ] 在 VPS `mosquitto_pub -h 127.0.0.1 -t tuppy/announce -m "测试广播"`，固件弹出 announce 弹层并 TTS 播报
- [ ] 屏显 Tuppy 状态页（提议数/待办数/健康）可切出、内容正确
- [ ] 阶段 2 通过标记：状态区 + 弹层 + 看板页均可见可用

---

## 阶段 3：BOOT 键 / 电源键手势

> 代码 ✅（待烧录验证）。

**BOOT 键（GPIO 0）**
- [ ] 短按：官方切换对话（开始/停止）正常
- [ ] 长按：官方音量调节正常
- [ ] **双击**：发布 `tuppy/button double`（静音牌）→ VPS 侧停止推送。验证：VPS 订阅 `mosquitto_sub -h 127.0.0.1 -t tuppy/button` 能看到 `double` 事件
- [ ] **三击**：发布 `tuppy/button triple`（隐私牌）→ VPS 侧断听断上报。验证能看到 `triple` 事件

**电源键（AXP2101 PEK，I2C INTSTS2 0x49）**
- [ ] 短按：屏显提示"电源键 快捷录入"
- [ ] 双击：屏显看板页切换
- [ ] 长按：原生 4s 关机（Tuppy 不占用，不冲突）
- [ ] 三击：屏显提示"电源键 家庭广播(预留)"

> ⚠️ VPS 侧按键语义（double→停止推送一天？triple→怎么断）设计文档标注「待设计」，烧录验证只确认**事件能发到 VPS**，业务处理后续补。

---

## 语音录入主目标（MCP 双向，代码已通，回工作室复验）

> 已确认：触发词统一用 **"帮我记一下"**（"记一笔"被 ASR 听成"G比"）。

- [ ] 小智智控台 MCP 显示在线（stdio 桥接）
- [ ] 说"帮我记一下，牛奶 8/20 到期" → ASR → LLM → MCP add_entry → SQLite（source='voice'）
- [ ] 查库确认落库正确（title/分类/happened_at 对）
- [ ] 说"今天有什么事" → list_proposals 返回今天提议并语音答
- [ ] 相对日期解析观察："明天/下周三"是否误录（设计文档 1.3 待定项）

---

## 烧录后必做：回归生产推送

- [ ] 固件在线后，等次日 08:30 早班推送，确认手机收到且点击跳转正常
- [ ] 确认 MQTT 状态发布不影响官方语音对话（两通道并行互不干扰）
- [ ] 在 status.md 把「v0.3 固件改造」从「代码完成待烧录」改为「✅ 真机验收通过」+ 验收日期

---

## 失败排查速查

| 现象 | 可能原因 | 动作 |
|---|---|---|
| 屏黑 / 卡开机 | board 选错或 flash 失败 | 重 `menuconfig` 选对板型，`idf.py flash` 重烧 |
| MQTT 连不上 | VPS mosquitto 没起 / topic 错 | VPS `systemctl status mosquitto`；核对 `tuppy/status` topic |
| 按键无事件 | 手势计数窗口/IRQ 轮询问题 | 看固件日志 `tuppy_pek` / BOOT 中断；确认 50ms 轮询任务在跑 |
| 语音不落库 | MCP token 错 / 反代断 | 查 VPS MCP 进程日志；核对 Bearer token 与智控台配置 |
| announce 不播 | TTS 未接 / 弹层未绑定 | 确认固件 announce 回调绑定 TTS |

---

## 完成标准

全部阶段 0~3 勾选 + 语音主目标复验通过 + 次日推送回归正常 → v0.3 硬件验收通过，可关闭「待烧录」状态。
