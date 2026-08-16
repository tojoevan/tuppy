"""Tuppy v0.1 规则引擎：模板解释器。

规则存在 rules 表里，本模块只做解释。四模板：
gap（缺测）/ overlap（冲突）/ surge（突变）/ expiry（到期）。
两班职责见 docs/v0.1-design.md §13。
"""

import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent
DB_PATH = BASE / "tuppy.db"

PROPOSAL_LIMIT = 3
FREQ_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
FREQ_UNIT = {"daily": "天", "weekly": "周", "monthly": "月"}
SHIFT_CN = {"morning": "早班", "evening": "晚班"}


def now():
    return dt.datetime.now()


def today():
    return now().date()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建库 + 首建时播种种子规则 + 跑未应用迁移。幂等。"""
    import migrations

    conn = get_db()
    existed = conn.execute(
        "SELECT name FROM sqlite_master WHERE name='rules'"
    ).fetchone()
    conn.executescript((BASE / "schema.sql").read_text())
    if not existed:
        conn.executescript((BASE / "seed.sql").read_text())
    conn.commit()
    migrations.migrate(conn)
    conn.close()


def parse_dt(s):
    """宽容解析日期字符串。失败返回 None。"""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%m-%d", "%m/%d"):
        try:
            d = dt.datetime.strptime(s, fmt)
            if fmt in ("%m-%d", "%m/%d"):
                d = d.replace(year=today().year)
            return d
        except ValueError:
            continue
    return None


def _rule_hint(rule):
    cat = rule["category"] or "全部"
    return f"{rule['domain']}·{cat}·{rule['template']}"


def _hit(candidate, text, rule, shadow_type=None, entry_id=None):
    return {
        "is_candidate": candidate,
        "rule_id": rule["id"],
        "text": text,
        "rule_hint": _rule_hint(rule),
        "shadow_type": shadow_type,
        "entry_id": entry_id,
        "priority": rule["priority"],
    }


def _missed_periods(last_date, period, include_today):
    """从 last_date 起数，错过多少个应记录周期。"""
    due = last_date + dt.timedelta(days=period)
    limit = today() if include_today else today() - dt.timedelta(days=1)
    n = 0
    while due <= limit:
        n += 1
        due += dt.timedelta(days=period)
    return n


def _pending_for_rule(conn, rule_id, text=None):
    sql = "SELECT id FROM proposals WHERE rule_id=? AND status='pending'"
    args = [rule_id]
    if text:
        sql += " AND text=?"
        args.append(text)
    return conn.execute(sql, args).fetchone()


# ---------- 模板 1：缺测 gap ----------

def scan_gap(conn, rule, params, shift):
    freq = params.get("frequency", "daily")
    max_gap = int(params.get("max_gap", 1))
    period = FREQ_DAYS.get(freq, 1)
    last = conn.execute(
        "SELECT * FROM entries WHERE domain=? AND category=?"
        " ORDER BY happened_at DESC LIMIT 1",
        (rule["domain"], rule["category"]),
    ).fetchone()
    if not last:
        return None  # 无记录习惯基线，不开口
    last_dt = parse_dt(last["happened_at"])
    if not last_dt:
        return None
    # 冷启动：缺测只从"开始使用 Tuppy"起算（该类别首条数据的录入日）。
    # 历史导入的空白不算缺测，否则刚导入 30 天历史就被轰炸。
    first = conn.execute(
        "SELECT created_at FROM entries WHERE domain=? AND category=?"
        " ORDER BY id LIMIT 1",
        (rule["domain"], rule["category"]),
    ).fetchone()
    base = last_dt.date()
    if first:
        try:
            watch_start = dt.date.fromisoformat(first["created_at"][:10])
            if watch_start > base:
                base = watch_start
        except ValueError:
            pass
    # 人称放在括号里，避免"妈"+"的"拼接出歧义文本
    name = rule["category"] or rule["domain"]
    if last["person"]:
        name = f"{name}（{last['person']}）"
    unit = FREQ_UNIT.get(freq, "天")
    if shift == "morning":
        missed = _missed_periods(base, period, include_today=False)
        if missed < max_gap:
            return None
        text = f"{name}有 {missed} {unit}没记了"
        if last_dt.date() < today():
            text += "，今天也还没记"
    else:
        missed = _missed_periods(base, period, include_today=True)
        if missed < max_gap + 1:
            return None
        text = f"{name}连续 {missed} {unit}没记了"
    if _pending_for_rule(conn, rule["id"]):
        return None  # 已有未处理的同规则提议，不重复
    return _hit(True, text, rule)


# ---------- 模板 2：冲突 overlap ----------

def scan_overlap(conn, rule, params):
    check = params.get("check_between", "same_person")
    min_minutes = int(params.get("min_overlap_min", 0))
    rows = conn.execute(
        "SELECT * FROM entries WHERE domain=? AND status='open'"
        " AND happened_at >= ? ORDER BY happened_at",
        (rule["domain"], today().isoformat()),
    ).fetchall()
    events = []
    for r in rows:
        start = parse_dt(r["happened_at"])
        if not start:
            continue
        end = parse_dt(r["ended_at"]) if r["ended_at"] else None
        if end is None:
            if len(r["happened_at"].strip()) == 10:
                end = start.replace(hour=23, minute=59, second=59)  # 全天事件
            else:
                end = start  # 点事件
        events.append((r, start, end))
    hits = []
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            ra, sa, ea = events[i]
            rb, sb, eb = events[j]
            if check == "same_person" and (ra["person"] or "") != (rb["person"] or ""):
                continue
            if max(sa, sb) > min(ea, eb):
                continue
            minutes = (min(ea, eb) - max(sa, sb)).total_seconds() / 60
            if minutes < min_minutes:
                continue
            fmt = lambda d: d.strftime("%m-%d %H:%M") if (d.hour or d.minute) else d.strftime("%m-%d")
            text = (f"{ra['title'] or '未命名'}撞了{rb['title'] or '未命名'}"
                    f"（{fmt(sa)} vs {fmt(sb)}）")
            if _pending_for_rule(conn, rule["id"], text):
                continue
            hits.append(_hit(True, text, rule))
    return hits


# ---------- 模板 3：突变 surge ----------

def scan_surge(conn, rule, params):
    rows = conn.execute(
        "SELECT happened_at, amount FROM entries WHERE domain=? AND category=?"
        " AND amount IS NOT NULL ORDER BY happened_at",
        (rule["domain"], rule["category"]),
    ).fetchall()
    if not rows:
        return None
    earliest = parse_dt(rows[0]["happened_at"])
    if not earliest:
        return None
    days_of_data = (today() - earliest.date()).days
    this_month = today().replace(day=1)
    last_month = (this_month - dt.timedelta(days=1)).replace(day=1)
    cur_sum = prev_sum = 0.0
    for r in rows:
        d = parse_dt(r["happened_at"])
        if not d:
            continue
        if d.year == this_month.year and d.month == this_month.month:
            cur_sum += r["amount"]
        elif d.year == last_month.year and d.month == last_month.month:
            prev_sum += r["amount"]
    label = rule["category"] or rule["domain"]
    ratio = cur_sum / prev_sum if prev_sum > 0 else 0.0
    threshold = float(params.get("ratio", 1.3))
    min_history = int(params.get("min_history_days", 30))
    min_amount = float(params.get("min_amount", 50))
    if days_of_data < min_history:
        if prev_sum > 0 and ratio > threshold:
            return _hit(
                False,
                f"{label}比上月高 {(ratio - 1) * 100:.0f}%，数据才 {days_of_data} 天，"
                f"看满 {min_history} 天再判断",
                rule, shadow_type="基线不足",
            )
        return None
    if prev_sum <= 0:
        return None  # 上月无数据，无基线
    pct = (ratio - 1) * 100
    if ratio >= threshold and (cur_sum - prev_sum) >= min_amount:
        return _hit(
            True,
            f"{label}比上月高 {pct:.0f}%（上月 {prev_sum:.0f}，本月 {cur_sum:.0f}）",
            rule,
        )
    if 1.0 < ratio < threshold:
        return _hit(
            False,
            f"{label}比上月高 {pct:.0f}%，低于 {threshold * 100:.0f}% 阈值，持续观察",
            rule, shadow_type="低于阈值",
        )
    if ratio >= threshold:
        return _hit(
            False,
            f"{label}比上月高 {pct:.0f}%，但差额只有 {cur_sum - prev_sum:.0f}，"
            f"低于 {min_amount:.0f} 门槛，先不说",
            rule, shadow_type="低于阈值",
        )
    return None


# ---------- 模板 4：到期 expiry ----------

def scan_expiry(conn, rule, params):
    days_before = int(params.get("days_before", 3))
    recurring = bool(params.get("recurring", False))
    period_days = int(params.get("period_days", 30))
    rows = conn.execute(
        "SELECT * FROM entries WHERE domain=? AND status IN ('open','notified')"
        " ORDER BY happened_at",
        (rule["domain"],),
    ).fetchall()
    hits = []
    for r in rows:
        due = parse_dt(r["happened_at"])
        if not due:
            continue
        if recurring and due.date() < today():
            # 到期已过未处理：顺延周期，重新开放
            while due.date() < today():
                due += dt.timedelta(days=period_days)
            conn.execute(
                "UPDATE entries SET happened_at=?, status='open' WHERE id=?",
                (due.strftime("%Y-%m-%d %H:%M:%S"), r["id"]),
            )
            r = conn.execute(
                "SELECT * FROM entries WHERE id=?", (r["id"],)
            ).fetchone()
        if r["status"] == "notified":
            continue  # 提醒过不再盯
        days_left = (due.date() - today()).days
        if days_left > days_before:
            continue
        if days_left < 0:
            text = f"{r['title']}已经到期 {-days_left} 天"
        elif days_left == 0:
            text = f"{r['title']}今天到期"
        else:
            text = f"{r['title']}还有 {days_left} 天到期"
        if _pending_for_rule(conn, rule["id"], text):
            continue
        hits.append(_hit(True, text, rule, entry_id=r["id"]))
    return hits


# ---------- 打扰预算 ----------

DEFAULT_QUOTA = 2
MIN_QUOTA = 1


def current_quota(conn):
    """当前每日推送配额。无记录 = 默认。"""
    row = conn.execute(
        "SELECT quota FROM budget_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["quota"] if row else DEFAULT_QUOTA


def pushed_today(conn):
    """今天已推次数（不含 weekly 心跳——心跳独立通道不占预算）。"""
    return conn.execute(
        "SELECT COUNT(*) c FROM push_log WHERE date=? AND shift!='weekly'",
        (today().isoformat(),),
    ).fetchone()["c"]


def quota_adjust(conn, action, quota, reason):
    conn.execute(
        "INSERT INTO budget_log (date, action, quota, reason) VALUES (?,?,?,?)",
        (today().isoformat(), action, quota, reason),
    )


def auto_adjust_quota(conn):
    """晚班调用。连续忽略 → 降配额；连续响应 → 恢复默认。

    判断窗口：最近 3 天每天都有推送且全部零响应 → -1（最低 1）。
              最近 5 天每天都有推送且全部有响应 → 恢复默认。
    """
    quota = current_quota(conn)
    days = conn.execute(
        "SELECT date, SUM(responded) r, COUNT(*) c FROM push_log"
        " WHERE shift!='weekly' GROUP BY date ORDER BY date DESC LIMIT 5"
    ).fetchall()
    if len(days) >= 3 and all(
        d["c"] > 0 and d["r"] == 0 for d in days[:3]
    ):
        if quota > MIN_QUOTA:
            quota_adjust(
                conn, "adjust_down", quota - 1,
                "连续 3 天推送你都没理，我少说一点",
            )
        return
    if len(days) >= 5 and all(
        d["c"] > 0 and d["r"] == d["c"] for d in days[:5]
    ):
        if quota < DEFAULT_QUOTA:
            quota_adjust(
                conn, "adjust_up", DEFAULT_QUOTA,
                "连续 5 天你都有回应，恢复默认",
            )


# ---------- 两班 ----------

def check_previous_shift(conn):
    """缺班检测：早班查昨晚晚班，晚班查今早早班。返回错误列表。"""
    errors = []
    if now().hour < 12:  # 早班时段
        y = (today() - dt.timedelta(days=1)).isoformat()
        row = conn.execute(
            "SELECT id FROM health WHERE date=? AND shift='evening'", (y,)
        ).fetchone()
        if not row:
            errors.append("昨晚没上工，今天补上")
    return errors


def check_row_anomaly(conn):
    """entries 行数较昨日突变 >20% 记警告。"""
    t = today().isoformat()
    y = (today() - dt.timedelta(days=1)).isoformat()
    cur = conn.execute(
        "SELECT COUNT(*) c FROM entries WHERE date(created_at)=?", (t,)
    ).fetchone()["c"]
    prev = conn.execute(
        "SELECT COUNT(*) c FROM entries WHERE date(created_at)=?", (y,)
    ).fetchone()["c"]
    if prev > 0 and abs(cur - prev) / prev > 0.2:
        return [f"数据行数异常波动（昨 {prev}，今 {cur}）"]
    return []


def apply_feedback(conn):
    """晚班批处理：过期 pending + 降权。"""
    cutoff = (now() - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE proposals SET status='expired',"
        " resolved_at=datetime('now','localtime')"
        " WHERE status='pending' AND created_at < ?", (cutoff,),
    )
    for rule in conn.execute(
        "SELECT * FROM rules WHERE status='propose'"
    ).fetchall():
        res = conn.execute(
            "SELECT status FROM proposals WHERE rule_id=? ORDER BY id DESC LIMIT 10",
            (rule["id"],),
        ).fetchall()

        def trailing(status):
            n = 0
            for r in res:
                if r["status"] == status:
                    n += 1
                else:
                    break
            return n

        n_exp, n_rej = trailing("expired"), trailing("rejected")
        if n_exp >= 4:
            downgrade(conn, rule, f"连续 {n_exp} 次没理，降为观察")
        elif n_rej >= 3:
            downgrade(conn, rule, f"连续 {n_rej} 次说不用，降为观察")


def downgrade(conn, rule, reason):
    conn.execute("UPDATE rules SET status='observe' WHERE id=?", (rule["id"],))
    conn.execute(
        "INSERT INTO rule_log (rule_id, action, reason) VALUES (?,?,?)",
        (rule["id"], "downgrade", reason),
    )


def fill_push_response(conn):
    """晚班回填：今天推送对应的内容是否有响应。

    早班推送 → 对应 pending proposals 当天是否被 kept/rejected。
    晚班推送 → 对应 todos 当天是否有 done。
    """
    rows = conn.execute(
        "SELECT id, shift FROM push_log WHERE date=?"
        " AND responded=0 AND shift!='weekly'",
        (today().isoformat(),),
    ).fetchall()
    for p in rows:
        if p["shift"] == "morning":
            responded = conn.execute(
                "SELECT COUNT(*) c FROM proposals WHERE shift='morning'"
                " AND date(created_at)=? AND status IN ('kept','rejected')",
                (today().isoformat(),),
            ).fetchone()["c"]
        else:
            responded = conn.execute(
                "SELECT COUNT(*) c FROM todos WHERE done=1 AND done_at IS NOT NULL"
                " AND date(done_at)=?",
                (today().isoformat(),),
            ).fetchone()["c"]
        if responded:
            conn.execute(
                "UPDATE push_log SET responded=1 WHERE id=?", (p["id"],)
            )


def backup_db():
    backups = BASE / "backups"
    backups.mkdir(exist_ok=True)
    shutil.copy(DB_PATH, backups / f"tuppy.db.{today().isoformat()}")
    for f in sorted(backups.glob("tuppy.db.*"), reverse=True)[7:]:
        f.unlink()


def run_shift(shift):
    """一个班次：自检 → 扫描 → 限额 → 写提议/影子 → （晚班）反馈+备份。"""
    if shift not in ("morning", "evening"):
        raise ValueError(f"unknown shift: {shift}")
    conn = get_db()
    errors = check_previous_shift(conn) + check_row_anomaly(conn)
    try:
        candidates, shadows = [], []
        for rule in conn.execute(
            "SELECT * FROM rules WHERE status='propose'"
            " ORDER BY priority DESC, id"
        ).fetchall():
            params = json.loads(rule["params"] or "{}")
            try:
                if rule["kind"] == "habit" and rule["template"] == "gap":
                    res = scan_gap(conn, rule, params, shift)
                elif rule["template"] == "overlap":
                    res = scan_overlap(conn, rule, params)
                elif rule["template"] == "surge":
                    res = scan_surge(conn, rule, params)
                elif rule["template"] == "expiry":
                    res = scan_expiry(conn, rule, params)
                else:
                    continue
                if isinstance(res, dict):
                    res = [res]
                for h in res or []:
                    if h["is_candidate"]:
                        candidates.append(h)
                    else:
                        shadows.append(h)
            except Exception as e:  # 单条规则死，不让整班死
                errors.append(f"规则 #{rule['id']} {_rule_hint(rule)} 报错：{e}")
        ordered = sorted(candidates, key=lambda c: -c["priority"])
        for i, h in enumerate(ordered):
            if i < PROPOSAL_LIMIT:
                conn.execute(
                    "INSERT INTO proposals (rule_id, entry_id, text, status,"
                    " shift) VALUES (?,?,?,?,?)",
                    (h["rule_id"], h.get("entry_id"), h["text"],
                     "pending", shift),
                )
                if h.get("entry_id"):
                    conn.execute(
                        "UPDATE entries SET status='notified' WHERE id=?",
                        (h["entry_id"],),
                    )
            else:
                h["shadow_type"] = "挤掉"
                shadows.append(h)
        for s in shadows:
            conn.execute(
                "INSERT INTO shadow (date, item_text, rule_hint, source_type,"
                " rule_id) VALUES (?,?,?,?,?)",
                (today().isoformat(), s["text"], s["rule_hint"],
                 s["shadow_type"], s["rule_id"]),
            )
        if shift == "evening":
            apply_feedback(conn)
            fill_push_response(conn)
            auto_adjust_quota(conn)
            backup_db()
        conn.execute(
            "INSERT INTO health (date, shift, status, error) VALUES (?,?,?,?)",
            (today().isoformat(), shift,
             "error" if errors else "ok", "; ".join(errors)),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        errors.append(str(e))
        conn.execute(
            "INSERT INTO health (date, shift, status, error) VALUES (?,?,?,?)",
            (today().isoformat(), shift, "error", "; ".join(errors)),
        )
        conn.commit()
        raise
    finally:
        conn.close()
