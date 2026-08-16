"""Tuppy MCP 服务：ESP32 语音终端的工具接口。

小智官方服务（xiaozhi-esp32-server）通过 MCP 调用这里的工具，
LLM 负责把用户的话解析成工具参数，工具返回 LLM 友好的短文本。

设计见 docs/v0.3-design.md §1。
鉴权：xiaozhi MCP 配置 headers 带 Authorization: Bearer <token>，
token 存 .env 的 TUPPY_MCP_TOKEN。
"""

import datetime as dt
import os

from mcp.server.fastmcp import FastMCP

import engine


def _load_dotenv():
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

# 运行方式：stdio 子进程，由 scripts/mcp_pipe.py 桥接到小智官方 MCP 接入点。
# 鉴权由接入点 token 处理（MCP_ENDPOINT 里带），本服务不出网、不监听。
mcp = FastMCP("tuppy")


def _db():
    return engine.get_db()


def _today():
    return dt.date.today().isoformat()


# ---------- 录入 ----------

@mcp.tool()
def add_entry(
    domain: str,
    happened_at: str,
    category: str = "",
    person: str = "",
    amount: float | None = None,
    value: str = "",
    title: str = "",
    note: str = "",
) -> str:
    """录一条数据到 Tuppy。

    Args:
        domain: 域（健康/账本/日程/物品/缴费/车辆/宠物/信用卡/证件/孩子/...）
        happened_at: 事件日期，ISO 格式 YYYY-MM-DD（可带 HH:MM）
        category: 域内分类（电费/水费/吃药/体重/...），可空
        person: 谁的事（妈妈/女儿/我），可空
        amount: 金额（账本用）
        value: 数值文本（健康用，如 140/88）
        title: 标题（日程/物品名）
        note: 备注
    """
    if not engine.parse_dt(happened_at):
        return "日期格式不对，请用 YYYY-MM-DD 格式重说一遍。"
    conn = _db()
    conn.execute(
        "INSERT INTO entries (domain, category, person, happened_at, amount,"
        " value, title, note, source) VALUES (?,?,?,?,?,?,?,?,'voice')",
        (domain.strip(), category.strip(), person.strip(), happened_at,
         amount, value.strip(), title.strip(), note.strip()),
    )
    conn.commit()
    conn.close()
    label = f"{person}的" if person else ""
    return f"记下了：{label}{category or title or domain} {happened_at}"


# ---------- 查询 ----------

@mcp.tool()
def list_proposals() -> str:
    """今天的提议。"""
    conn = _db()
    rows = conn.execute(
        "SELECT text, status FROM proposals"
        " WHERE date(created_at)=date('now','localtime')"
        " ORDER BY id DESC"
    ).fetchall()
    conn.close()
    if not rows:
        return "今天没有提议。"
    status_cn = {"pending": "还没处理", "kept": "已记下",
                 "rejected": "你说不用", "expired": "没理"}
    parts = [f"{i + 1}. {r['text']}（{status_cn.get(r['status'], r['status'])}）"
             for i, r in enumerate(rows)]
    return "今天有这些：\n" + "\n".join(parts)


@mcp.tool()
def list_todos() -> str:
    """未完成的待办。"""
    conn = _db()
    rows = conn.execute(
        "SELECT text, due FROM todos WHERE done=0 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    if not rows:
        return "待办是空的。"
    parts = []
    for i, r in enumerate(rows):
        line = f"{i + 1}. {r['text']}"
        if r["due"]:
            overdue = "（已到期）" if r["due"] <= _today() else f"（截止 {r['due']}）"
            line += overdue
        parts.append(line)
    return "待办：\n" + "\n".join(parts)


@mcp.tool()
def query_entries(domain: str, category: str = "", days: int = 30) -> str:
    """查记录。

    Args:
        domain: 域，必填
        category: 分类，可空（空 = 全部分类）
        days: 往回看几天，默认 30
    """
    conn = _db()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    sql = ("SELECT happened_at, category, person, amount, value, title"
           " FROM entries WHERE domain=? AND happened_at>=?")
    args = [domain.strip(), since]
    if category.strip():
        sql += " AND category=?"
        args.append(category.strip())
    rows = conn.execute(sql + " ORDER BY happened_at DESC LIMIT 20",
                        args).fetchall()
    conn.close()
    if not rows:
        return f"最近 {days} 天没有「{domain}」的记录。"
    parts = []
    for r in rows:
        bits = [r["happened_at"][:10]]
        if r["category"]:
            bits.append(r["category"])
        if r["amount"] is not None:
            amt = int(r["amount"]) if r["amount"] == int(r["amount"]) \
                else r["amount"]
            bits.append(f"{amt}元")
        if r["value"]:
            bits.append(r["value"])
        if r["title"]:
            bits.append(r["title"])
        parts.append(" · ".join(bits))
    return f"「{domain}」最近 {days} 天：\n" + "\n".join(parts)


@mcp.tool()
def weekly_stats() -> str:
    """本周数字：说了几次、听进去几次、超预算几次。"""
    conn = _db()
    monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    stats = conn.execute(
        "SELECT status, COUNT(*) c FROM proposals WHERE created_at>=?"
        " GROUP BY status", (monday.isoformat(),),
    ).fetchall()
    counts = {s["status"]: s["c"] for s in stats}
    over = conn.execute(
        "SELECT COUNT(*) c FROM shadow WHERE source_type='超预算'"
        " AND date>=?", (monday.isoformat(),),
    ).fetchone()["c"]
    conn.close()
    total = sum(counts.values())
    kept = counts.get("kept", 0)
    line = f"这周我说了 {total} 次，你听进去 {kept} 次"
    if over:
        line += f"，{over} 次超预算没推"
    return line + "。"


if __name__ == "__main__":
    # stdio 模式：由 mcp_pipe.py spawn 并桥接到官方接入点
    mcp.run(transport="stdio")
