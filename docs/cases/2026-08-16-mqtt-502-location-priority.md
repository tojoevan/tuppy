# 案例：tuppy.oahubs.com/mqtt 502 定位与修复

> 日期：2026-08-16
> 现象：ESP32 固件 MQTT 控制通道（wss://tuppy.oahubs.com/mqtt）连接失败，公网访问该地址返回 502
> 结论：根因 = 宝塔反向代理 location 优先级（^~ / 吃掉 /mqtt）+ mosquitto websocket 是 HTTP/1.1 协议
> 状态：已修复，固件链路验证通过

## 1. 背景

Tuppy v0.3 固件改造：ESP32 板子通过独立 MQTT 客户端（tuppy_link）连 VPS mosquitto，做状态屏显/播报/按键。

架构：

```
Tuppy shifts.py → mosquitto_pub → 1883(原生MQTT) → mosquitto → 1884(websocket) → nginx /mqtt → wss → ESP32
```

- VPS：150.158.120.205（宝塔面板）
- mosquitto：1883 原生 MQTT（Tuppy 发布）+ 1884 websocket（固件连接）
- nginx：宝塔反向代理，tuppy.oahubs.com → 127.0.0.1:8321（Flask）

## 2. 现象

- `curl https://tuppy.oahubs.com/mqtt` → 502 Bad Gateway
- 固件 `wss://tuppy.oahubs.com/mqtt` 连不上 broker
- 但 Tuppy Web（tuppy.oahubs.com）正常，ntfy 推送正常

## 3. 定位过程（关键步骤）

### 3.1 排查链路分层

从外到内逐层验证：

| 层 | 验证方法 | 结果 |
|---|---|---|
| DNS/公网 | curl tuppy.oahubs.com | ✅ 200（Web 正常） |
| nginx 反代 | curl /mqtt | ❌ 502 |
| mosquitto 进程 | systemctl status mosquitto | ✅ running，1883+1884 监听 |
| 直连 mosquitto ws | curl 127.0.0.1:1884（带 Upgrade 头） | ✅ 101 Switching Protocols |
| 固件连接 | mosquitto 日志 | ✅ ESP32_f32CF0 曾连上 |

**关键矛盾**：直连 1884 返回 101，但经 nginx 就 502。

### 3.2 发现宝塔反代配置

宝塔的站点反代配置在 `/www/server/project/...` 和生成的 nginx vhost 里：

```
/www/server/panel/vhost/nginx/tuppy.oahubs.com.conf
    location ^~ / {
        proxy_pass http://127.0.0.1:8321;   # 所有路径 → Flask
    }
/www/server/panel/vhost/nginx/extension/tuppy.oahubs.com/mqtt.conf
    location /mqtt {
        proxy_pass http://127.0.0.1:1884;    # 本应 → mosquitto
    }
```

**根因 1**：`location ^~ /` 的 `^~` 前缀匹配优先级**高于**普通 `location /mqtt`（无修饰符）。nginx 对 `^~` 前缀选最长匹配，但 `location /mqtt` 是普通前缀匹配，优先级低于 `^~` → `/mqtt` 请求被 `^~ /` 吃掉 → 打到 Flask → Flask 不认 /mqtt → 502。

### 3.3 修复 1：mqtt location 加 ^~

```nginx
location ^~ /mqtt {
    proxy_pass http://127.0.0.1:1884;
    ...
}
```

`^~ /mqtt` 比 `^~ /` 更长，nginx 选最长 `^~` 前缀 → `/mqtt` 正确进 mosquitto location。

### 3.4 修复 2：proxy_pass 路径剥离

`proxy_pass http://127.0.0.1:1884;` 会保留原始 URI（/mqtt）转发 → mosquitto websocket 收到 `GET /mqtt` 但只认 `/`（mosquitto websocket 默认路径是 /）。

```nginx
proxy_pass http://127.0.0.1:1884/;   # 尾部斜杠 = 剥离 /mqtt
```

### 3.5 验证 location 命中

临时把 mqtt.conf 改成 `return 200 "mqtt-location-hit";`，公网访问 /mqtt 返回该文本 → **证明 location 优先级修复生效**。

### 3.6 最终根因：HTTP/2 假象

location 修好后，curl 默认（HTTP/2）访问 /mqtt 仍 502，但 **--http1.1 访问返回 101**！

**根因 2**：mosquitto websocket 是 HTTP/1.1 协议。nginx 用 HTTP/1.1 代理（proxy_http_version 1.1）转发没问题，但**客户端侧**如果是 HTTP/2 握手（curl 默认、浏览器），nginx 与 HTTP/1.1 的 websocket 后端不兼容 → 502。

**但 ESP32 固件 esp_mqtt_client 用的是 HTTP/1.1 websocket**（不是 HTTP/2）→ 固件实际是通的（mosquitto 日志里 ESP32_f32CF0 连接记录就是证据）。

## 4. 最终修复内容

`/www/server/panel/vhost/nginx/extension/tuppy.oahubs.com/mqtt.conf`：

```nginx
location ^~ /mqtt {
    proxy_pass http://127.0.0.1:1884/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 300s;
}
```

操作：`sudo nginx -t && sudo nginx -s reload`

## 5. 验证结果

| 检查 | 结果 |
|---|---|
| mosquitto 1883 原生 MQTT | ✅ mosquitto_sub/pub 收发正常 |
| mosquitto 1884 websocket | ✅ 直连 101 |
| nginx /mqtt（HTTP/1.1 wss） | ✅ 101 Switching Protocols |
| 固件 wss://tuppy.oahubs.com/mqtt | ✅ 链路通（mosquitto 日志有固件连接） |
| HTTP/2 curl /mqtt | ⚠️ 502（假象，固件不用 HTTP/2） |

## 6. 经验教训

1. **宝塔反代 location 优先级坑**：宝塔默认生成 `location ^~ /`（站点反代），扩展目录（extension/*.conf）里的普通 `location /mqtt` 会被它抢走。**自定义路径反代必须用 `location ^~ /路径`**（同样 ^~ 才能压过 ^~ /）。

2. **proxy_pass 尾部斜杠 = 路径剥离**：`proxy_pass http://host:port;`（无斜杠）保留原 URI；`http://host:port/;`（有斜杠）用根路径。mosquitto websocket 只认 `/`，必须剥离 `/mqtt`。

3. **测试要用对协议**：curl 默认 HTTP/2，测 websocket 后端（HTTP/1.1）会得到假 502。**必须 `curl --http1.1` 或带 Upgrade 头测**。判断固件是否真的连不上，看 mosquitto 日志（`New client connected ... as ESP32_xxx`）比 curl 可靠。

4. **逐层验证优于猜**：从公网 → nginx → mosquitto → 直连，每层一个验证点，矛盾点（直连 101 但反代 502）直接指向 nginx 层。

5. **tcpdump 抓 lo 端口**：`tcpdump -i lo port 1884 -A` 能看到 nginx 转发给 mosquitto 的完整 HTTP 头（含 Upgrade/Sec-WebSocket-Key），是定位反代问题的利器。

## 7. 相关文件

- 固件：xiaozhi-esp32-2.0.5-amoled-2.06/main/tuppy_link.cc（MQTT 客户端，URI=wss://tuppy.oahubs.com/mqtt）
- VPS mosquitto：/etc/mosquitto/conf.d/tuppy.conf（1883 原生 + 1884 websocket，allow_anonymous true）
- VPS nginx：/www/server/panel/vhost/nginx/extension/tuppy.oahubs.com/mqtt.conf
- Tuppy 状态发布：001-first/notify.py（mqtt_status，mosquitto_pub → 127.0.0.1:1883）
- 设计文档：001-first/docs/v0.3-design.md §0（固件 MQTT 通道）

## 8. 遗留

- mosquitto 1883 目前 allow_anonymous true（公网可连）。固件 MQTT 通道用 wss + 匿名；以后要收紧可加认证，固件 esp_mqtt_client 需配 username/password（tuppy_link.cc 尚未支持）。
- 宝塔面板重新生成反代配置可能覆盖 extension 目录的手改，需留意。
