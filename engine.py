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


def _hit(candidate, text, rule, shadow_type=None, entry_id=None, due_date=None):
    return {
        "is_candidate": candidate,
        "rule_id": rule["id"],
        "text": text,
        "rule_hint": _rule_hint(rule),
        "shadow_type": shadow_type,
        "entry_id": entry_id,
        "due_date": due_date,
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
    # pending（待用户采纳）+ kept（已采纳/recurring 自动落待办）都算已处理，
    # 避免同一规则一天内早晚班重复出提议或重复落待办。
    sql = "SELECT id FROM proposals WHERE rule_id=? AND status IN ('pending','kept')"
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
    subject = rule["category"] or rule["domain"]
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
        hits.append(_hit(True, text, rule, entry_id=r["id"],
                         due_date=due.date().isoformat()))
    # recurring 冷启动：凭 anchor_date 推算下一个未来到期日。
    # 护栏：anchor 只在「该 domain 历史上真发生过（有 entry）」或「用户主动确认过」
    # 时才算数——系统 seed 编造的锚点（无 entry 支撑）一律静默，不替用户发明事务。
    if recurring and not rows and rule["anchor_date"]:
        has_history = conn.execute(
            "SELECT 1 FROM entries WHERE domain=? LIMIT 1", (rule["domain"],)
        ).fetchone()
        if not has_history:
            return hits
        due = parse_dt(rule["anchor_date"])
        if due:
            while due.date() <= today():
                due += dt.timedelta(days=period_days)
            days_left = (due.date() - today()).days
            # 仅临近（≤ days_before）或已过期才出提醒，避免一上来就轰炸全年
            if days_left <= days_before:
                text = (f"{subject}下次到期还有 {days_left} 天"
                        if days_left >= 0 else f"{subject}已过期 {-days_left} 天")
                if not _pending_for_rule(conn, rule["id"], text):
                    hits.append(_hit(True, text, rule,
                                     due_date=due.date().isoformat()))
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
                recurring = bool(params.get("recurring", False))
                for h in res or []:
                    if recurring:
                        h["auto_todo"] = True
                    if h["is_candidate"]:
                        candidates.append(h)
                    else:
                        shadows.append(h)
            except Exception as e:  # 单条规则死，不让整班死
                errors.append(f"规则 #{rule['id']} {_rule_hint(rule)} 报错：{e}")
        ordered = sorted(candidates, key=lambda c: -c["priority"])
        for i, h in enumerate(ordered):
            if i < PROPOSAL_LIMIT:
                auto = bool(h.get("auto_todo"))
                status = "kept" if auto else "pending"
                cur = conn.execute(
                    "INSERT INTO proposals (rule_id, entry_id, text, status,"
                    " shift) VALUES (?,?,?,?,?)",
                    (h["rule_id"], h.get("entry_id"), h["text"],
                     status, shift),
                )
                pid = cur.lastrowid
                if h.get("entry_id"):
                    conn.execute(
                        "UPDATE entries SET status='notified' WHERE id=?",
                        (h["entry_id"],),
                    )
                # recurring 规则命中：周期事务本就该办，自动落待办，不打扰确认
                if auto:
                    conn.execute(
                        "INSERT INTO todos (proposal_id, text, due) VALUES (?,?,?)",
                        (pid, h["text"], h.get("due_date")),
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


# ---------- 微问答：从规则派生的轻量信息补充 ----------

def _domain_has_entry(conn, dom, cat):
    """该 domain(+category) 是否已有对应 entry。有则视为信息已存在，
    微问答的 expiry/surge 补信息题应跳过（避免「你的信用卡」这种没指定哪条的尴尬）。"""
    if cat:
        row = conn.execute(
            "SELECT 1 FROM entries WHERE domain=? AND category=? LIMIT 1",
            (dom, cat),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM entries WHERE domain=? LIMIT 1", (dom,)
        ).fetchone()
    return bool(row)


def derive_questions(conn):
    """扫描已启用规则，按 template 派生微问答题。

    每题带稳定 key（qa:{template}:{domain}:{category}），前端答过/跳过后写入
    qa_state 不再问。返回 list[dict]：{key, kind, domain, category, q, hint, options?}
    - expiry：问到期日（填空日期）
    - surge：问上次数值（填空数字）
    - habit+gap：问今天记没记（选择 记了/还没）
    - overlap：跳过（冲突类不适合微问答）

    护栏：expiry/surge 题若 domain(+category) 已有 entry，则跳过——信息已存在，
    不该再用笼统问法补（如「你的信用卡」没指定哪张）。
    """
    out = []
    for rule in conn.execute(
        "SELECT * FROM rules WHERE status='propose'"
    ).fetchall():
        tpl = rule["template"]
        dom = rule["domain"]
        cat = rule["category"] or ""
        # 主语：有子类用「domain·子类」，无子类用「你的 domain」软化问法，
        # 避免「物品 的到期日」这类生硬且无解的病句。
        subject = f"{dom}·{cat}" if cat else f"你的{dom}"
        key = f"qa:{tpl}:{dom}:{cat}"
        if tpl in ("expiry", "surge"):
            # 已有 entry 则不问（信息已存在，且笼统问法无解）
            if _domain_has_entry(conn, dom, cat):
                continue
        if tpl == "expiry":
            out.append({
                "key": key, "kind": "fill", "domain": dom, "category": cat,
                "q": f"{subject} 的到期日是什么时候？",
                "hint": "填日期，如 2026-09-01 或 9/1",
                "field": "happened_at",
            })
        elif tpl == "surge":
            out.append({
                "key": key, "kind": "fill", "domain": dom, "category": cat,
                "q": f"上次 {subject} 是多少？",
                "hint": "填数字，如 128 或 230.5",
                "field": "amount",
            })
        elif tpl == "gap" and rule["kind"] == "habit":
            out.append({
                "key": key, "kind": "choice", "domain": dom, "category": cat,
                "q": f"今天 {subject} 记了吗？",
                "hint": "",
                "options": [
                    {"v": "yes", "t": "记了"},
                    {"v": "no", "t": "还没"},
                ],
                "field": "done_today",
            })
        # overlap 等其它模板暂不支持微问答
    return out


def _qa_done(conn, key):
    """只有真正答过（answered_at）才算完成；跳过（skipped_at）不算——
    跳过代表『当前不想答/没数据』，下次循环仍可再问。"""
    row = conn.execute(
        "SELECT answered_at FROM qa_state WHERE key=?", (key,)
    ).fetchone()
    if not row:
        return False
    return bool(row["answered_at"])


def next_question(conn):
    """从未答过的题里随机抽一道（循环随机问答；跳过不屏蔽，答过才停）。"""
    import random
    pool = [q for q in derive_questions(conn) if not _qa_done(conn, q["key"])]
    if not pool:
        return None
    return random.choice(pool)


def record_qa_skip(conn, key):
    conn.execute(
        "INSERT INTO qa_state (key, skipped_at) VALUES (?, datetime('now','localtime'))"
        " ON CONFLICT(key) DO UPDATE SET skipped_at=datetime('now','localtime')",
        (key,),
    )
    conn.commit()


def apply_qa_answer(conn, q, value):
    """把答案写成一条 entries（source='qa'），喂养数据库与判据。

    - fill+happened_at：value 解析为日期写 entries（domain/category 来自规则）
    - fill+amount：写一条 amount=value 的 entries
    - choice+done_today=yes：写一条 today 的 entries（表示今天记了）
       choice=no：只记 qa_state，不写 entries（避免噪音）
    返回写入的 entry id 或 None。
    """
    dom, cat = q["domain"], q["category"]
    today_iso = today().isoformat()
    entry_id = None
    if q["field"] == "happened_at":
        d = parse_dt(value)
        if d:
            conn.execute(
                "INSERT INTO entries (domain, category, happened_at, title,"
                " note, status, source) VALUES (?,?,?,?,?, 'open', 'qa')",
                (dom, cat, d.strftime("%Y-%m-%d %H:%M:%S"),
                 f"{cat or dom}到期日", f"微问答补充：{value}"),
            )
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # A 补充：recurring 规则把「上次/最近一次」回写为冷启动锚点，
            # 使 scan_expiry 能凭 anchor + period 推算下次到期（哪怕无历史 entry）。
            rule = conn.execute(
                "SELECT * FROM rules WHERE domain=? AND category=? AND template='expiry'",
                (dom, cat),
            ).fetchone()
            if rule and rule["params"]:
                try:
                    import json
                    is_recurring = json.loads(rule["params"]).get("recurring")
                except (json.JSONDecodeError, TypeError):
                    is_recurring = False
                if is_recurring:
                    conn.execute(
                        "UPDATE rules SET anchor_date=? WHERE id=?",
                        (d.strftime("%Y-%m-%d"), rule["id"]),
                    )
    elif q["field"] == "amount":
        try:
            amt = float(value)
        except (TypeError, ValueError):
            amt = None
        if amt is not None:
            conn.execute(
                "INSERT INTO entries (domain, category, happened_at, amount,"
                " title, note, status, source) VALUES (?,?,?,?,?,?, 'open', 'qa')",
                (dom, cat, today_iso, amt,
                 f"{cat or dom}数值", f"微问答补充：{value}"),
            )
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    elif q["field"] == "done_today" and value == "yes":
        conn.execute(
            "INSERT INTO entries (domain, category, happened_at, title,"
            " note, status, source) VALUES (?,?,?,?,?, 'open', 'qa')",
            (dom, cat, today_iso, f"{cat or dom}",
             f"微问答：今天记了"),
        )
        entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # 记 qa_state（无论是否写 entries，答过即停）
    conn.execute(
        "INSERT INTO qa_state (key, answered_at, kind) VALUES (?,"
        " datetime('now','localtime'), ?)"
        " ON CONFLICT(key) DO UPDATE SET answered_at=datetime('now','localtime')",
        (q["key"], q["kind"]),
    )
    conn.commit()
    return entry_id


def pick_today_top(conn):
    """挑今天最该处理的 1 条，供早班推送聚焦。

    规则：优先待办（todos, done=0）里 due 最近且未过期的；
    没有则退回 pending 提议里优先级最高的。都没有返回 None。
    返回 {text, url} 或 None。
    """
    t = today().isoformat()
    # 1) 待办：due 最近且未过期（含无 due 的排最后）
    row = conn.execute(
        "SELECT id, text, due FROM todos WHERE done=0"
        " AND (due IS NULL OR due >= ?)"
        " ORDER BY (due IS NULL), due ASC LIMIT 1",
        (t,),
    ).fetchone()
    if row:
        return {"text": row["text"], "url": "/todos"}
    # 2) 退回 pending 提议：按所属规则优先级最高
    row = conn.execute(
        "SELECT p.id, p.text, r.priority FROM proposals p"
        " JOIN rules r ON r.id=p.rule_id"
        " WHERE p.status='pending'"
        " ORDER BY r.priority DESC, p.id DESC LIMIT 1"
    ).fetchone()
    if row:
        return {"text": row["text"], "url": "/"}
    return None

