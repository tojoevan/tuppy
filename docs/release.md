# Tuppy 发布文档

## 版本规则

- v0.x 语义：x = 阶段（0.1 值守 / 0.2 推送 / 0.3 安卓……）
- 每版本完成判据：见该版本设计文档"完成的定义"章节
- 达成后写 CHANGELOG，记录实际数据（接受率、运行天数）

## 发布流程

1. 版本设计文档定稿（本仓库 docs/）
2. 实现 + 测试通过（pytest tests/）
3. 部署 VPS，跑满判据天数
4. 记录实际数字进 CHANGELOG
5. 由使用摩擦决定下一版本方向

## 部署（VPS，Ubuntu/Debian）

```bash
# 1. 拉代码
git clone https://github.com/tojoevan/tuppy.git
cd tuppy

# 2. 环境
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export TUPPY_SECRET=<随机串>   # 写进 .env，gitignore 已排除

# 3. systemd 托管（挂了自动重启）
# /etc/systemd/system/tuppy.service:
[Unit]
Description=Tuppy web
After=network.target

[Service]
WorkingDirectory=/path/to/tuppy
Environment=TUPPY_SECRET=<随机串>
ExecStart=/path/to/tuppy/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target

sudo systemctl enable --now tuppy

# 4. nginx 反代 + Basic Auth（Flask 零鉴权代码）
sudo apt install -y nginx apache2-utils
sudo htpasswd -c /etc/nginx/tuppy.htpasswd <用户名>
# /etc/nginx/sites-available/tuppy:
server {
    listen 80;
    location / {
        auth_basic "Tuppy";
        auth_basic_user_file /etc/nginx/tuppy.htpasswd;
        proxy_pass http://127.0.0.1:8321;
    }
}
sudo ln -s /etc/nginx/sites-available/tuppy /etc/nginx/sites-enabled/
sudo systemctl reload nginx

# 5. cron 两班
30 6 * * * cd /path/to/tuppy && .venv/bin/python shifts.py morning >> tuppy-cron.log 2>&1
0 22 * * * cd /path/to/tuppy && .venv/bin/python shifts.py evening >> tuppy-cron.log 2>&1
```

DB 每日备份轮转 7 份：晚班自动（engine.backup_db，backups/ 目录，gitignore 已排除）。

## 宝塔面板部署记录（2026-08-15 实际执行）

- 目录 `/www/wwwroot/tuppy.oahubs.com`，属组 www:www
- SSH 用户 ubuntu（非 root），sudo 免密
- 需要 `apt install python3.12-venv`（宝塔系统无 ensurepip）
- **systemd 必须设 `User=www`**：不设则以 root 运行，root 建的 tuppy.db www 写不了（readonly database）。这是本次踩的唯一坑
- **cron 必须装进 www 用户 crontab**（`sudo -u www crontab -`），与 systemd 同身份
- 反代：宝塔面板自建反代项目 → `http://127.0.0.1:8321`（用户侧配置，本仓库不涉及）
- 验证：18 测试 VPS 全过；录血压 → 早班 → 首页出提议"妈的血压有 1 天没记了，今天也还没记"

## 自动部署（2026-08-15）

- `/usr/local/bin/tuppy-deploy.sh` + root crontab `*/5` 轮询：fetch 比对 HEAD → 有变更 pull → **只有代码文件变更才 restart**（docs/README/CHANGELOG 变更只 pull 不重启）→ 重启后 curl 健康检查
- git 操作以 `sudo -u www` 身份跑（文件属主不变，避开之前的 root/www 身份坑）
- 首次需 `sudo -u www git config --global --add safe.directory /www/wwwroot/tuppy.oahubs.com`（dubious ownership）
- 不做 webhook：公网触发端点有攻击面，单人项目轮询足够
- **注意：schema.sql 变更不会自动迁移**，那种提交需手动处理，脚本只重启不管迁移

## ntfy 推送自建（2026-08-16）

- 装 `/usr/bin/ntfy` v2.27.0（deb，官方 sha256 校验后安装）
- 配置 `/etc/ntfy/server.yml`：
  - `listen-http: 127.0.0.1:2586`（只本机，公网走反代）
  - `base-url: https://ntfy.oahubs.com`（**ntfy 不支持子路径托管**，base-url 必须裸域名——踩坑记录）
  - `upstream-base-url: https://ntfy.sh`（iOS 及时推送必需，APNs 中转）
  - `behind-proxy: true`
  - `auth-file: /var/lib/ntfy/user.db` + `auth-default-access: deny-all`
  - `auth-users: tuppy:<bcrypt hash>:admin`（`printf 'pw\npw\n' | ntfy user hash` 生成）
  - `web-root: disable`
- systemd 自带（deb 包），`Restart=on-failure`
- 测试：带 auth publish/subscribe 通，无 auth 403
- Tuppy 侧：`notify.py` 用 ntfy（.env: TUPPY_NTFY_URL/TOPIC/USER/PASS）
- **VPS 连 GitHub 不稳**（curl 56 / 443 超时）：代码同步 fallback = scp 直传。auto-deploy cron 5 分钟轮询会在网络恢复后自动收敛，文件内容一致无冲突

## 版本记录

见 CHANGELOG.md。
