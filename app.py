"""Tuppy v0.1 web 终端：三动作五页面。

选择（按钮）/ 输入（表单+导入）/ 查看（提议/待办/影子/周报）。
无聊天框。voice 参照 docs/day-script.md。
"""

import csv
import datetime as dt
import hmac
import io
import json
import os
import uuid

from flask import (
    Flask, flash, redirect, render_template, request, send_from_directory,
    session, url_for
)

import engine


def _load_dotenv():
    """把 .env 合并进 os.environ（cron/systemd 不一定注入，进程内自读最稳）。"""
    f = engine.BASE / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("TUPPY_SECRET", "dev-secret-change-me")
app.permanent_session_lifetime = dt.timedelta(days=30)

# 登录密码独立于 session 密钥。部署时生成随机值写 .env。
TUPPY_PASSWORD = os.environ.get("TUPPY_PASSWORD", "tuppy-change-me")


VERSION = "0.1"


def git_version():
    """语义版本 + git 短 hash。版本号看阶段，hash 看部署是否生效。"""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=engine.BASE,
        )
        if out.returncode == 0:
            return f"{VERSION}.{out.stdout.strip()}"
    except Exception:
        pass
    return VERSION

SEED_DOMAINS = ["健康", "日程", "账本", "物品", "疫苗"]


@app.before_request
def ensure_db():
    if not engine.DB_PATH.exists():
        engine.init_db()


@app.before_request
def require_login():
    # static 与登录页免鉴权——PWA 图标/清单不被挡，登录页本身可达
    if request.path.startswith("/static/"):
        return None
    if request.path == "/login":
        return None
    if not session.get("authed"):
        return redirect(url_for("login"))


def _password_ok(candidate):
    return hmac.compare_digest(candidate, TUPPY_PASSWORD)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authed"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        if _password_ok(request.form.get("password", "")):
            session.permanent = True
            session["authed"] = True
            return redirect(url_for("index"))
        error = "密码不对。"
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/export")
def data_export():
    """数据是文件：下载完整 SQLite。"""
    return send_from_directory(
        engine.DB_PATH.parent, engine.DB_PATH.name, as_attachment=True,
        download_name=f"tuppy-{dt.date.today().isoformat()}.db",
    )


@app.route("/deploy", methods=["POST"])
def deploy_trigger():
    """写 trigger 文件。root cron 每分钟捡一次，捡到就跑部署脚本。

    Flask 是 www 用户，不直接跑 git/systemctl——零权限扩张。
    """
    trigger = engine.BASE / ".deploy-trigger"
    try:
        trigger.write_text("go")
        flash("已通知部署，一分钟内生效。刷新页面看版本号变化。")
    except OSError:
        flash("通知部署失败，稍后再试。")
    return redirect(url_for("index"))


def health_light(conn):
    """页面顶部健康灯：(颜色, 文案)。"""
    rows = conn.execute(
        "SELECT * FROM health WHERE created_at >="
        " datetime('now','localtime','-48 hours') ORDER BY id"
    ).fetchall()
    if not rows:
        return ("red", "超过 48 小时没有班次记录，cron 可能没配置")
    errs = [r for r in rows if r["status"] == "error"]
    if errs:
        return ("yellow", errs[-1]["error"] or "有报错")
    t = dt.date.today().isoformat()
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    if not any(r["date"] == y and r["shift"] == "evening" for r in rows):
        return ("yellow", "昨晚没上工，今天补上")
    if not any(r["date"] == t and r["shift"] == "morning" for r in rows):
        return ("yellow", "今早还没上工")
    return ("green", "两班正常")


@app.context_processor
def inject_light():
    conn = engine.get_db()
    light = health_light(conn)
    conn.close()
    return {"light": light, "version": git_version()}


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(engine.BASE / "static", filename)


@app.route("/")
def index():
    conn = engine.get_db()
    proposals = conn.execute(
        "SELECT p.*, r.domain, r.category, e.happened_at AS due_at"
        " FROM proposals p"
        " JOIN rules r ON r.id=p.rule_id"
        " LEFT JOIN entries e ON e.id=p.entry_id"
        " WHERE p.status IN ('pending','kept')"
        " AND date(p.created_at)=date('now','localtime')"
        " ORDER BY p.id DESC",
    ).fetchall()
    history = conn.execute(
        "SELECT * FROM proposals WHERE status IN ('rejected','expired')"
        " AND date(created_at)>=date('now','localtime','-7 days')"
        " ORDER BY id DESC LIMIT 10",
    ).fetchall()
    conn.close()
    hour = dt.datetime.now().hour
    pending = [p for p in proposals if p["status"] == "pending"]
    if 5 <= hour < 12:
        greeting = f"早。你睡的时候我看了下家里的事，{len(pending)} 件想跟你说：" \
            if pending else "早。你睡的时候我看了下，没什么要跟你说的。"
    else:
        greeting = f"有 {len(pending)} 件想跟你说：" \
            if pending else "今天没什么要跟你说的。"
    return render_template(
        "index.html", proposals=proposals, history=history, greeting=greeting
    )


@app.route("/proposal/<int:pid>/keep", methods=["POST"])
def keep(pid):
    conn = engine.get_db()
    p = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if p and p["status"] == "pending":
        # 到期类提议：从关联 entry 取截止日
        due = None
        if p["entry_id"]:
            e = conn.execute(
                "SELECT happened_at FROM entries WHERE id=?", (p["entry_id"],)
            ).fetchone()
            if e:
                due = e["happened_at"][:10]
        conn.execute(
            "UPDATE proposals SET status='kept',"
            " resolved_at=datetime('now','localtime') WHERE id=?", (pid,),
        )
        conn.execute(
            "INSERT INTO todos (proposal_id, text, due) VALUES (?,?,?)",
            (pid, p["text"], due),
        )
        conn.commit()
        flash("好，记在待办里了。")
    conn.close()
    return redirect(url_for("index"))


@app.route("/proposal/<int:pid>/reject", methods=["POST"])
def reject(pid):
    conn = engine.get_db()
    p = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if p and p["status"] == "pending":
        conn.execute(
            "UPDATE proposals SET status='rejected',"
            " resolved_at=datetime('now','localtime') WHERE id=?", (pid,),
        )
        conn.commit()
        flash("好，这条不说了。")
    conn.close()
    return redirect(url_for("index"))


@app.route("/todos")
def todos():
    conn = engine.get_db()
    offset = max(0, request.args.get("offset", 0, type=int))
    open_todos = conn.execute(
        "SELECT * FROM todos WHERE done=0 ORDER BY id DESC"
    ).fetchall()
    done_todos = conn.execute(
        "SELECT * FROM todos WHERE done=1 ORDER BY done_at DESC"
        " LIMIT 10 OFFSET ?", (offset,),
    ).fetchall()
    done_total = conn.execute(
        "SELECT COUNT(*) c FROM todos WHERE done=1"
    ).fetchone()["c"]
    conn.close()
    return render_template(
        "todos.html", open_todos=open_todos, done_todos=done_todos,
        done_total=done_total, offset=offset,
        today=dt.date.today().isoformat(),
    )


@app.route("/todo/<int:tid>/done", methods=["POST"])
def todo_done(tid):
    conn = engine.get_db()
    conn.execute(
        "UPDATE todos SET done=1, done_at=datetime('now','localtime')"
        " WHERE id=? AND done=0", (tid,),
    )
    conn.commit()
    conn.close()
    flash("记下了，这条我归档了。")
    return redirect(url_for("todos"))


@app.route("/entries")
def entries():
    conn = engine.get_db()
    offset = max(0, request.args.get("offset", 0, type=int))
    domain_filter = request.args.get("domain", "").strip()
    where, args = "", []
    if domain_filter:
        where = " WHERE domain=?"
        args.append(domain_filter)
    recent = conn.execute(
        f"SELECT * FROM entries{where} ORDER BY id DESC LIMIT 10 OFFSET ?",
        args + [offset],
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) c FROM entries{where}", args
    ).fetchone()["c"]
    all_domains = [
        r["domain"] for r in conn.execute(
            "SELECT DISTINCT domain FROM entries ORDER BY domain"
        )
    ]
    conn.close()
    return render_template(
        "entries.html", recent=recent, total=total, offset=offset,
        domains=SEED_DOMAINS, domain_filter=domain_filter,
        all_domains=all_domains,
    )


@app.route("/entry/add", methods=["POST"])
def entry_add():
    domain = (request.form.get("domain", "").strip()
              or request.form.get("domain_custom", "").strip())
    happened = (request.form.get("happened_date", "").strip()
                + (" " + request.form.get("happened_time", "").strip()
                   if request.form.get("happened_time", "").strip() else ""))
    ended_date = request.form.get("ended_date", "").strip()
    ended_time = request.form.get("ended_time", "").strip()
    ended = (ended_date + (" " + ended_time if ended_time else "")) or None
    if not domain or not engine.parse_dt(happened):
        flash("没记下：域和日期是必填的。")
        return redirect(url_for("entries"))
    if ended and not engine.parse_dt(ended):
        flash("没记下：结束时间格式不对。")
        return redirect(url_for("entries"))
    conn = engine.get_db()
    conn.execute(
        "INSERT INTO entries (domain, category, person, happened_at, ended_at,"
        " amount, value, title, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            domain,
            request.form.get("category", "").strip(),
            request.form.get("person", "").strip(),
            happened,
            ended,
            request.form.get("amount", "").strip() or None,
            request.form.get("value", "").strip() or None,
            request.form.get("title", "").strip(),
            request.form.get("note", "").strip(),
        ),
    )
    conn.commit()
    conn.close()
    flash("记下了。")
    return redirect(url_for("entries"))


@app.route("/entry/<int:eid>/edit", methods=["GET", "POST"])
def entry_edit(eid):
    conn = engine.get_db()
    row = conn.execute(
        "SELECT * FROM entries WHERE id=?", (eid,)
    ).fetchone()
    if not row:
        conn.close()
        flash("没找到这条。")
        return redirect(url_for("entries"))
    if request.method == "POST":
        domain = (request.form.get("domain", "").strip()
                  or request.form.get("domain_custom", "").strip())
        happened = (request.form.get("happened_date", "").strip()
                    + (" " + request.form.get("happened_time", "").strip()
                       if request.form.get("happened_time", "").strip() else ""))
        ended_date = request.form.get("ended_date", "").strip()
        ended_time = request.form.get("ended_time", "").strip()
        ended = (ended_date + (" " + ended_time if ended_time else "")) or None
        if not domain or not engine.parse_dt(happened):
            flash("没改：域和日期是必填的。")
            return redirect(url_for("entry_edit", eid=eid))
        if ended and not engine.parse_dt(ended):
            flash("没改：结束时间格式不对。")
            return redirect(url_for("entry_edit", eid=eid))
        conn.execute(
            "UPDATE entries SET domain=?, category=?, person=?, happened_at=?,"
            " ended_at=?, amount=?, value=?, title=?, note=? WHERE id=?",
            (
                domain,
                request.form.get("category", "").strip(),
                request.form.get("person", "").strip(),
                happened,
                ended,
                request.form.get("amount", "").strip() or None,
                request.form.get("value", "").strip() or None,
                request.form.get("title", "").strip(),
                request.form.get("note", "").strip(),
                eid,
            ),
        )
        conn.commit()
        conn.close()
        flash("改好了。")
        return redirect(url_for("entries"))
    conn.close()
    return render_template("entry_edit.html", row=row, domains=SEED_DOMAINS)


@app.route("/entry/<int:eid>/delete", methods=["POST"])
def entry_delete(eid):
    conn = engine.get_db()
    conn.execute("DELETE FROM entries WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    flash("删掉了。")
    return redirect(url_for("entries"))


# ---------- 导入 ----------

CSV_FIELDS = ["domain", "person", "happened_at", "category",
              "amount", "value", "title", "note"]


def _validate_row(row):
    if not row.get("domain", "").strip():
        return False, "缺 domain"
    if not engine.parse_dt(row.get("happened_at", "")):
        return False, f"日期解析失败：{row.get('happened_at', '')}"
    if row.get("amount", "").strip():
        try:
            float(row["amount"])
        except ValueError:
            return False, f"金额解析失败：{row['amount']}"
    return True, None


@app.route("/import/csv", methods=["POST"])
def import_csv():
    file = request.files.get("file")
    if not file:
        flash("没收到文件。")
        return redirect(url_for("entries"))
    content = file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "domain" not in reader.fieldnames \
            or "happened_at" not in reader.fieldnames:
        flash("CSV 首行必须是 header，且至少含 domain 和 happened_at 两列。")
        return redirect(url_for("entries"))
    batch = uuid.uuid4().hex
    conn = engine.get_db()
    ok = bad = 0
    bad_rows = []
    for i, row in enumerate(reader, start=2):
        valid, reason = _validate_row(row)
        conn.execute(
            "INSERT INTO import_staging (batch, row_json, valid, reason)"
            " VALUES (?,?,?,?)",
            (batch, json.dumps(row, ensure_ascii=False), valid, reason),
        )
        if valid:
            ok += 1
        else:
            bad += 1
            bad_rows.append((i, reason))
    conn.commit()
    conn.close()
    return render_template(
        "import_preview.html", batch=batch, ok=ok, bad=bad,
        bad_rows=bad_rows, kind="csv",
    )


@app.route("/import/ics", methods=["POST"])
def import_ics():
    from icalendar import Calendar

    file = request.files.get("file")
    if not file:
        flash("没收到文件。")
        return redirect(url_for("entries"))
    person = request.form.get("person", "").strip()
    try:
        cal = Calendar.from_ical(file.read())
    except Exception:
        flash("ICS 解析失败。")
        return redirect(url_for("entries"))
    batch = uuid.uuid4().hex
    conn = engine.get_db()
    ok = bad = 0
    bad_rows = []
    for comp in cal.walk("VEVENT"):
        start, summary = comp.get("DTSTART"), comp.get("SUMMARY")
        if not start or not summary:
            bad += 1
            bad_rows.append((0, "缺 DTSTART 或 SUMMARY"))
            continue
        sdt, edt = start.dt, comp.get("DTEND")
        if isinstance(sdt, dt.datetime):
            sdt = sdt.replace(tzinfo=None)
            edt = edt.dt.replace(tzinfo=None) if edt else None
            row = {
                "domain": "日程",
                "person": person,
                "happened_at": sdt.strftime("%Y-%m-%d %H:%M:%S"),
                "ended_at": edt.strftime("%Y-%m-%d %H:%M:%S") if edt else None,
                "title": str(summary),
                "note": str(comp.get("DESCRIPTION", ""))[:200],
                "location": str(comp.get("LOCATION", "")),
            }
        else:  # 全天事件
            row = {
                "domain": "日程",
                "person": person,
                "happened_at": sdt.isoformat(),
                "title": str(summary),
                "note": str(comp.get("DESCRIPTION", ""))[:200],
                "location": str(comp.get("LOCATION", "")),
            }
        conn.execute(
            "INSERT INTO import_staging (batch, row_json, valid) VALUES (?,?,?)",
            (batch, json.dumps(row, ensure_ascii=False), 1),
        )
        ok += 1
    conn.commit()
    conn.close()
    return render_template(
        "import_preview.html", batch=batch, ok=ok, bad=bad,
        bad_rows=bad_rows, kind="ics",
    )


def _dedupe_exists(conn, row):
    # CSV 空字段是 '' → None；数值字符串 → float，与库内 REAL 列同型比较
    amount = row.get("amount") or None
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            pass
    return conn.execute(
        "SELECT id FROM entries WHERE domain=? AND person=?"
        " AND happened_at=? AND title=?"
        " AND COALESCE(amount,-999999)=COALESCE(?,-999999) LIMIT 1",
        (row.get("domain", ""), row.get("person", ""),
         row.get("happened_at", ""), row.get("title", ""),
         amount),
    ).fetchone()


@app.route("/import/confirm", methods=["POST"])
def import_confirm():
    batch = request.form.get("batch", "")
    conn = engine.get_db()
    staging = conn.execute(
        "SELECT * FROM import_staging WHERE batch=? AND valid=1", (batch,)
    ).fetchall()
    inserted = skipped = 0
    for s in staging:
        row = json.loads(s["row_json"])
        if _dedupe_exists(conn, row):
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO entries (domain, category, person, happened_at,"
            " ended_at, amount, value, title, note, source)"
            " VALUES (?,?,?,?,?,?,?,?,?, 'import')",
            (
                row.get("domain", ""),
                row.get("category", ""),
                row.get("person", ""),
                row.get("happened_at", ""),
                row.get("ended_at") or None,
                row.get("amount") or None,
                row.get("value") or None,
                row.get("title", ""),
                row.get("note", "") or (row.get("location") or ""),
            ),
        )
        inserted += 1
    conn.execute(
        "DELETE FROM import_staging WHERE batch=?", (batch,)
    )
    conn.commit()
    conn.close()
    flash(f"导入完成：{inserted} 条写入，{skipped} 条重复跳过。")
    return redirect(url_for("entries"))


# ---------- 规则浏览 ----------

TEMPLATE_CN = {"gap": "缺测", "overlap": "冲突",
               "surge": "突变", "expiry": "到期"}
STATUS_CN = {"propose": "提议", "observe": "观察", "archive": "归档"}


@app.route("/rules")
def rules_page():
    conn = engine.get_db()
    rules = conn.execute("SELECT * FROM rules ORDER BY status, id").fetchall()
    rates = rule_hit_rate(conn)
    conn.close()
    return render_template(
        "rules.html", rules=rules, rates=rates,
        template_cn=TEMPLATE_CN, status_cn=STATUS_CN,
    )


@app.route("/rule/<int:rid>/delete", methods=["POST"])
def rule_delete(rid):
    conn = engine.get_db()
    conn.execute("DELETE FROM rules WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    flash("规则删掉了。")
    return redirect(url_for("rules_page"))


# ---------- 规则导入/导出 ----------

VALID_TEMPLATES = ("gap", "overlap", "surge", "expiry")
VALID_KINDS = ("habit", "detection")


def rule_hit_rate(conn):
    """每条规则的历史命中率：kept/(kept+rejected+expired)。样本<5 返回 None。"""
    out = {}
    rows = conn.execute(
        "SELECT rule_id, status, COUNT(*) c FROM proposals"
        " WHERE status IN ('kept','rejected','expired')"
        " GROUP BY rule_id, status"
    ).fetchall()
    agg = {}
    for r in rows:
        agg.setdefault(r["rule_id"], {})[r["status"]] = r["c"]
    for rule_id, counts in agg.items():
        kept = counts.get("kept", 0)
        total = kept + counts.get("rejected", 0) + counts.get("expired", 0)
        out[rule_id] = round(kept / total, 2) if total >= 5 else None
    return out


def _rules_export(conn):
    rules = conn.execute(
        "SELECT kind, domain, category, template, params, priority"
        " FROM rules ORDER BY id"
    ).fetchall()
    return {
        "format": "tuppy-rules",
        "version": 1,
        "exported_at": dt.date.today().isoformat(),
        "rules": [
            {
                "kind": r["kind"],
                "domain": r["domain"],
                "category": r["category"],
                "template": r["template"],
                "params": json.loads(r["params"] or "{}"),
                "priority": r["priority"],
            }
            for r in rules
        ],
    }


def _rules_import(conn, rules):
    """导入规则。返回 (inserted, skipped, rejected)。"""
    inserted = skipped = rejected = 0
    for r in rules:
        kind = r.get("kind")
        template = r.get("template")
        params = r.get("params", {})
        if kind not in VALID_KINDS or template not in VALID_TEMPLATES:
            rejected += 1
            continue
        if not isinstance(params, dict):
            rejected += 1
            continue
        exists = conn.execute(
            "SELECT id FROM rules WHERE domain=? AND category=?"
            " AND template=?",
            (r.get("domain", ""), r.get("category", ""), template),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO rules (kind, domain, category, template, params,"
            " priority) VALUES (?,?,?,?,?,?)",
            (
                kind,
                r.get("domain", ""),
                r.get("category", ""),
                template,
                json.dumps(params, ensure_ascii=False),
                int(r.get("priority", 5)),
            ),
        )
        inserted += 1
    return inserted, skipped, rejected


@app.route("/rules/export")
def rules_export():
    conn = engine.get_db()
    payload = _rules_export(conn)
    conn.close()
    resp = app.response_class(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
    )
    resp.headers["Content-Disposition"] = (
        "attachment; filename=tuppy-rules.json"
    )
    return resp


@app.route("/rules/import", methods=["POST"])
def rules_import():
    payload = None
    if request.form.get("json"):
        try:
            payload = json.loads(request.form["json"])
        except json.JSONDecodeError:
            flash("导入失败：JSON 解析不了。")
            return redirect(url_for("rules_page"))
    else:
        file = request.files.get("file")
        if file:
            try:
                payload = json.loads(file.read())
            except (json.JSONDecodeError, UnicodeDecodeError):
                flash("导入失败：JSON 解析不了。")
                return redirect(url_for("rules_page"))
    if not payload or not isinstance(payload.get("rules"), list):
        flash("导入失败：格式不对，需要 {\"rules\": [...]}")
        return redirect(url_for("rules_page"))
    conn = engine.get_db()
    inserted, skipped, rejected = _rules_import(conn, payload["rules"])
    conn.commit()
    conn.close()
    flash(f"导入完成：{inserted} 条新增，{skipped} 条已存在跳过，{rejected} 条拒绝。")
    return redirect(url_for("rules_page"))


# ---------- 影子报告 ----------

@app.route("/shadow")
def shadow():
    conn = engine.get_db()
    grouped = {}
    for it in conn.execute(
        "SELECT * FROM shadow ORDER BY date DESC, id DESC"
    ).fetchall():
        grouped.setdefault(it["date"], []).append(it)
    obs_rules = conn.execute(
        "SELECT * FROM rules WHERE status='observe' ORDER BY id"
    ).fetchall()
    obs_map = {}
    for rule in obs_rules:
        items = [it for its in grouped.values() for it in its
                 if it["rule_id"] == rule["id"]][:5]
        if items:
            obs_map[rule["id"]] = (rule, items)
    conn.close()
    return render_template(
        "shadow.html", grouped=grouped, obs_map=obs_map
    )


@app.route("/shadow/revive", methods=["POST"])
def shadow_revive():
    rule_ids = request.form.getlist("rule_ids")
    conn = engine.get_db()
    for rid in rule_ids:
        rule = conn.execute(
            "SELECT * FROM rules WHERE id=? AND status='observe'", (rid,)
        ).fetchone()
        if rule:
            conn.execute(
                "UPDATE rules SET status='propose' WHERE id=?", (rid,)
            )
            conn.execute(
                "INSERT INTO rule_log (rule_id, action, reason) VALUES (?,?,?)",
                (rid, "upgrade", "你在影子里把它叫回来了"),
            )
    conn.commit()
    conn.close()
    flash("好，明天开始说这些。")
    return redirect(url_for("shadow"))


# ---------- 周报 ----------

@app.route("/weekly")
def weekly():
    conn = engine.get_db()
    monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    sunday = monday + dt.timedelta(days=6)
    stats = conn.execute(
        "SELECT status, COUNT(*) c FROM proposals WHERE created_at >= ?"
        " GROUP BY status",
        (monday.isoformat(),),
    ).fetchall()
    counts = {s["status"]: s["c"] for s in stats}
    total = sum(counts.values())
    kept = counts.get("kept", 0)
    rejected = counts.get("rejected", 0)
    expired = counts.get("expired", 0)
    # 语音录入占比：判断语音是否真降低了录入摩擦
    voice_count = conn.execute(
        "SELECT COUNT(*) c FROM entries WHERE source='voice'"
        " AND date(created_at)>=? AND date(created_at)<=?",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchone()["c"]
    entries_count = conn.execute(
        "SELECT COUNT(*) c FROM entries WHERE date(created_at)>=?"
        " AND date(created_at)<=?",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchone()["c"]
    changes = conn.execute(
        "SELECT l.*, r.domain, r.category, r.template FROM rule_log l"
        " JOIN rules r ON r.id=l.rule_id WHERE l.created_at >= ?"
        " ORDER BY l.id DESC",
        (monday.isoformat(),),
    ).fetchall()
    for c in changes:
        name = f"{c['domain']}·{c['category'] or '全部'}"
        c["label"] = f"「{name}」{'重新开始说' if c['action'] == 'upgrade' else '降为观察'}"
    shadow_top = conn.execute(
        "SELECT * FROM shadow WHERE date >= ? ORDER BY id DESC LIMIT 5",
        (monday.isoformat(),),
    ).fetchall()
    undone = conn.execute(
        "SELECT * FROM todos WHERE done=0 ORDER BY id DESC"
    ).fetchall()
    # 最近 8 周命中率趋势（信任面板 v0.1）
    trend = []
    for wk in range(7, -1, -1):
        wk_start = monday - dt.timedelta(weeks=wk)
        wk_end = wk_start + dt.timedelta(days=7)
        s = conn.execute(
            "SELECT status, COUNT(*) c FROM proposals WHERE created_at >= ?"
            " AND created_at < ? AND status IN ('kept','rejected','expired')"
            " GROUP BY status",
            (wk_start.isoformat(), wk_end.isoformat()),
        ).fetchall()
        counts = {x["status"]: x["c"] for x in s}
        kept_w = counts.get("kept", 0)
        total_w = kept_w + counts.get("rejected", 0) + counts.get("expired", 0)
        trend.append({
            "label": wk_start.strftime("%m-%d"),
            "total": total_w,
            "rate": round(kept_w / total_w * 100) if total_w else None,
        })
    # 打扰预算段
    pushes = conn.execute(
        "SELECT COUNT(*) c FROM push_log WHERE date>=? AND date<=?"
        " AND shift!='weekly'",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchone()["c"]
    responded = conn.execute(
        "SELECT COUNT(*) c FROM push_log WHERE date>=? AND date<=?"
        " AND shift!='weekly' AND responded=1",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchone()["c"]
    over_budget = conn.execute(
        "SELECT COUNT(*) c FROM shadow WHERE source_type='超预算'"
        " AND date>=? AND date<=?",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchone()["c"]
    quota = conn.execute(
        "SELECT quota FROM budget_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if total and (rejected + expired) / total > 0.4:
        next_line = "下周我少说一点，说准一点。"
    else:
        next_line = "下周我照旧。"
    return render_template(
        "weekly.html", monday=monday, sunday=sunday, total=total,
        kept=kept, rejected=rejected, expired=expired,
        changes=changes, shadow_top=shadow_top, undone=undone,
        next_line=next_line, trend=trend,
        pushes=pushes, responded=responded, over_budget=over_budget,
        quota=quota["quota"] if quota else 2,
        voice_count=voice_count, voice_entries=entries_count,
    )


@app.route("/pushes")
def pushes():
    conn = engine.get_db()
    # 每条推送实时计算「10 分钟内响应」：
    # 早班 → 当天 morning 提议在推送后 10 分钟内被接受/拒绝；
    # 晚班 → 当天待办在推送后 10 分钟内完成。周报心跳不统计。
    rows = conn.execute(
        """
        SELECT p.id, p.date, p.shift, p.text, p.created_at, p.responded,
          CASE WHEN p.shift='weekly' THEN -1
               WHEN p.shift='morning' THEN COALESCE((
                 SELECT 1 FROM proposals
                 WHERE shift='morning' AND date(created_at)=p.date
                   AND status IN ('kept','rejected') AND resolved_at IS NOT NULL
                   AND resolved_at >= p.created_at
                   AND resolved_at <= datetime(p.created_at, '+10 minutes')
                 LIMIT 1), 0)
               ELSE COALESCE((
                 SELECT 1 FROM todos
                 WHERE done=1 AND done_at IS NOT NULL
                   AND date(done_at)=p.date
                   AND done_at >= p.created_at
                   AND done_at <= datetime(p.created_at, '+10 minutes')
                 LIMIT 1), 0)
          END AS responded_10m
        FROM push_log p
        ORDER BY p.created_at DESC
        """
    ).fetchall()
    total = sum(1 for r in rows if r["shift"] != "weekly")
    r10 = sum(1 for r in rows if r["responded_10m"] == 1)
    rsame = sum(1 for r in rows if r["responded"] == 1 and r["shift"] != "weekly")
    conn.close()
    return render_template(
        "pushes.html",
        rows=rows,
        total=total,
        r10=r10,
        r10_rate=round(r10 / total * 100) if total else None,
        rsame=rsame,
        rsame_rate=round(rsame / total * 100) if total else None,
    )


if __name__ == "__main__":
    # 只监听本机——公网入口由宝塔反代负责，绕开反代直连不可达
    app.run(host="127.0.0.1", port=8321)
