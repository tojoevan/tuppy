# Tuppy 部署运作流程（未白 × joevan 协作手册）

> 目的：把「代码怎么上生产、谁负责哪一步、出问题怎么兜底」固化成单一事实源。
> 后期忘了就回看这一篇，不用重新对齐。
> 最后更新：2026-08-23

---

## 1. 架构与地址

| 项 | 值 |
|---|---|
| 域名 | `tuppy.oahubs.com`（Flask 登录页） |
| **真实 VPS IP** | **`150.158.120.205`**（宝塔面板，Ubuntu，SSH 用户 `ubuntu` sudo 免密） |
| 项目目录 | `/www/wwwroot/tuppy.oahubs.com`（属主 `www:www`） |
| 反代 | 宝塔面板反代 → `127.0.0.1:8321`（Flask 本机监听） |
| 进程托管 | systemd（`Restart=always` / `on-failure`） |
| ntfy 推送 | `https://ntfy.oahubs.com`（topic `tuppy`，用户 `tuppy`，iOS 走 ntfy.sh APNs 中转） |
| MQTT | VPS mosquitto 1883（原生）+ 1884（ws），nginx `/mqtt` 反代 → ESP32 固件 |

> ⚠️ **DNS 注意**：未白所在环境把 `tuppy.oahubs.com` 解析到 `198.18.4.16`（RFC 2544 保留段，非正常公网 IP，疑似 DNS 拦截/代理黑洞）。因此**未白侧用域名验证线上不可信**，一切以「IP `150.158.120.205` 直连」为准。joevan 在自己网络里域名解析正常。

---

## 2. 自动部署（主通道）

机制：`/usr/local/bin/tuppy-deploy.sh` + **root cron 每 5 分钟**轮询 GitHub。

> ⚠️ **实测（2026-08-23）：自动部署并未如期生效。** 未白用 IP 直连查线上 HEAD，发现 VPS 一直停在 `9598b26`（远早于最新 `8bd90e4`），`app.py` 里没有 `/pushes` 路由。说明 cron/脚本实际没跑成功或 fetch 失败。**不能假设 push 后 5 分钟自动上线**——每次发布后务必以「IP 直连查 HEAD」（§7）或「面板看版本号」确证，未生效就手动 fetch+reset+重启（§3/§7）。自动部署为何失效待排查（crontab 是否还在、脚本是否存活、VPS→GitHub 连通）。

流程：
```
cron */5 → fetch 比对 HEAD
  → 有变更：git reset --hard origin/main
    → 只有「代码文件」变更才 restart（docs/README/CHANGELOG 变更只 pull 不重启）
    → 重启后 curl 健康检查
```
- git 操作以 `sudo -u www` 身份跑（避开 root/www 属主坑）。
- 用 `reset --hard`（非 `pull`）：scp 直传会弄脏工作树，`reset` 安全（`tuppy.db`/`.env`/`backups` 均 gitignored，不受影响）。
- **不做 webhook**：公网触发端点有攻击面，单人项目轮询足够。

### 关键区分：代码变更 vs schema 变更
| 改动类型 | 自动部署是否够 | 处理 |
|---|---|---|
| 只动 `app.py` / 模板 / 静态资源 | ✅ 够 | push 后 ≤5 分钟自动 pull + restart |
| 动 `schema.sql`（改表结构） | ❌ 不够 | 脚本只重启、**不自动迁移** → 需 joevan 手动跑迁移（见 §3 / migrations.py） |

> 本次 `/pushes` 功能（2026-08-23，commit `8bd90e4`）：只动 `app.py` + 模板 + `docs/status.md`，**未碰 schema** → 自动部署即可生效，无需手动迁移。

---

## 3. 手动部署兜底（宝塔面板）

当自动部署没生效（如 VPS 连 GitHub 不稳、或 schema 变更需迁移）时：

1. **joevan 登录宝塔面板** → 找到 `tuppy` 项目 → 点「重启」（或停止+启动）。
2. 若需拉最新代码：VPS 上 `sudo -u www git -C /www/wwwroot/tuppy.oahubs.com reset --hard origin/main`（或面板里手动 pull）。
3. 若涉及 schema 变更：参考 `migrations.py`，在 VPS 上对生产库跑对应迁移 SQL，再重启。
4. 重启后验证：面板看进程状态 green，或 curl 健康检查（见 §4）。

> 手动重启是「兜底」不是「日常」。日常就是 push，等 5 分钟自动生效。

---

## 4. 上线验证（三选一）

| 方法 | 怎么做 | 适用 |
|---|---|---|
| **看版本号**（最直观） | 登录 tuppy.oahubs.com → 页面右上 header 显示 git 短 hash（格式 `v8bd90e4`） | joevan 日常肉眼确认 |
| **点更新按钮** | 页面 header「更新」按钮 → POST `/deploy` 写 `.deploy-trigger` → root cron 每分钟捡信跑部署（比等 5 分钟快） | 想立即生效时 |
| **直连查 HEAD**（最确凿） | `ssh ubuntu@150.158.120.205 'cd /www/wwwroot/tuppy.oahubs.com && git rev-parse --short HEAD'` → 对比 GitHub 最新 commit | 未白侧无域名解析时确证 |

健康检查：`curl -s -o /dev/null -w "%{http_code}" https://tuppy.oahubs.com/login` 应返回 `200`（根路径 `/` 会 302 跳登录，属正常拦截，非故障）。

---

## 5. 分工约定（未白 × joevan）

| 角色 | 负责 |
|---|---|
| **未白（WorkBuddy 助手）** | 1) 写代码/修 bug；2) 本地验证（py_compile / SQL 逻辑 / pytest / Flask test client）；3) `git commit` + `git push origin main`；4) 维护本文档与 status.md/README；5) 需要时 SSH 直连 IP 查线上 HEAD 确证 |
| **joevan（你）** | 1) 触发宝塔面板 `tuppy` 项目重启（兜底/手动迁移后）；2) 登录站点看 header 版本号确认上线；3) 提供 VPS 访问信息（IP 已给：`150.158.120.205`）；4) 最终业务确认（功能是否符合预期） |

> 默认节奏：**未白 push → 等 5 分钟自动部署 → joevan 看版本号确认**。只在自动部署失效或 schema 变更时，才需要 joevan 动面板。

---

## 6. 已知坑与注意事项

- **VPS 连 GitHub 不稳**（历史：curl 56 / 443 超时）：自动部署 cron 5 分钟轮询会在网络恢复后自动收敛；曾有 scp 直传 fallback，现已不需要（正常走 push → 自动部署）。
- **宝塔反代 location 优先级**（案例 `2026-08-16-mqtt-502`）：宝塔默认生成 `location ^~ /` 会吃掉自定义 `location /mqtt`。自定义路径反代必须用 `location ^~ /路径` 才能压过默认。宝塔重生成配置可能覆盖手改，需留意。
- **ntfy base-url 必须裸域名**：ntfy 不支持子路径托管，`base-url: https://ntfy.oahubs.com`（非子路径）。
- **鉴权是 Flask 登录页 + 签名 session**（非 nginx Basic Auth）：`.env` 的 `TUPPY_PASSWORD` / `TUPPY_SECRET` 由 app.py 启动时进程内读文件（systemd 环境注入曾不可靠）。宝塔面板若还开着 Basic Auth 目录保护会双层锁，需手动关。
- **`/static/` 免鉴权**（PWA 资产），其余全锁，未登录 302 到 `/login`。
- **本地 `tuppy.db` 为空**（未播种）：真数据全在生产 VPS，本地只是代码副本，别拿本地库当生产看。

---

## 7. 一键速查

```bash
# 未白侧：推完代码后，直连 IP 确证线上版本（需 SSH 密钥可用）
ssh ubuntu@150.158.120.205 'cd /www/wwwroot/tuppy.oahubs.com && git rev-parse --short HEAD && git log --oneline -1'

# 健康检查（joevan 侧，域名解析正常时）
curl -s -o /dev/null -w "login: %{http_code}\n" https://tuppy.oahubs.com/login

# VPS 侧手动拉最新 + 重启（joevan 在面板点重启等效）
sudo -u www git -C /www/wwwroot/tuppy.oahubs.com reset --hard origin/main
```

## 8. 实测记录（2026-08-23）

- 未白 push `/pushes`（commit `8bd90e4`）后，误以为自动部署 5 分钟内生效。
- 因 DNS 把 `tuppy.oahubs.com` 解析到 `198.18.4.16`（非真实 IP），未白无法用域名确证，改用 **IP `150.158.120.205` 直连 SSH**。
- 实测线上 HEAD = `9598b26`，`app.py` 无 `/pushes` 路由 → **自动部署当时未生效**。
- 修复：未白 `sudo -u www git fetch && reset --hard origin/main` 把 VPS 拉到 `8bd90e4`（`/pushes` 路由数 0→1）。**服务进程仍是旧代码，需 joevan 在宝塔面板点 tuppy 项目「重启」生效**。
- 遗留：自动部署 cron 为何失效待排查。
