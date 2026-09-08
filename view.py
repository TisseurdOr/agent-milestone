"""Read-only viewer: render the trail store as a self-contained HTML page."""
import html
import os
import sqlite3

from store import DEFAULT_DB_PATH, TrailStore

_ROLE_STYLE = {
    "user": ("#2563eb", "你"),
    "assistant": ("#059669", "Agent"),
    "tool": ("#dc2626", "工具"),
}


def _esc(s):
    return html.escape(str(s or ""))


def _clip(s, n=600):
    s = str(s or "")
    return s if len(s) <= n else s[:n] + f"…（截断，共 {len(s)} 字）"


def render(db_path: str = DEFAULT_DB_PATH, out_path: str | None = None) -> str:
    store = TrailStore(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name, step_hash FROM milestones ORDER BY rowid DESC"
    ).fetchall()
    total = conn.execute("SELECT count(*) FROM steps").fetchone()[0]
    role_counts = dict(
        conn.execute("SELECT role, count(*) FROM steps GROUP BY role").fetchall()
    )

    body = []
    body.append(
        f"<p class='stat'>里程碑 <b>{len(rows)}</b> 个 · step <b>{total}</b> 条 · "
        f"user {role_counts.get('user', 0)} / assistant {role_counts.get('assistant', 0)} / tool {role_counts.get('tool', 0)}</p>"
    )
    for name, tip in rows:
        steps = store.checkout(name)
        body.append(
            f"<details><summary><b>{_esc(name)}</b>"
            f"<span class='hash'>{_esc(tip[:12])}</span>"
            f"<span class='n'>{len(steps)} 步</span></summary>"
        )
        for s in steps:
            role = s.get("role", "")
            color, label = _ROLE_STYLE.get(role, ("#6b7280", role))
            body.append(f"<div class='step' style='border-left:3px solid {color}'>")
            body.append(f"<div class='role' style='color:{color}'>{label}</div>")
            if role == "tool":
                body.append(
                    f"<div class='toolname'>{_esc(s.get('tool_name', ''))}</div>"
                )
                if s.get("tool_args"):
                    body.append(f"<pre>{_esc(_clip(s['tool_args']))}</pre>")
                if s.get("tool_result"):
                    body.append(f"<pre>{_esc(_clip(s['tool_result']))}</pre>")
            else:
                body.append(f"<div class='content'>{_esc(_clip(s.get('content', '')))}</div>")
            body.append("</div>")
        body.append("</details>")

    html_doc = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-milestone · 轨迹查看</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#111}}
h1{{font-size:22px}}
.stat{{color:#555}} .stat b{{color:#111}}
details{{border:1px solid #e5e7eb;border-radius:8px;margin:12px 0;padding:10px 14px}}
summary{{cursor:pointer;font-size:15px}}
.hash{{color:#9ca3af;font-family:monospace;font-size:12px;margin-left:8px}}
.n{{color:#9ca3af;font-size:12px;margin-left:8px}}
.step{{margin:8px 0;padding:6px 10px;background:#f9fafb;border-radius:4px}}
.role{{font-size:12px;font-weight:600;margin-bottom:2px}}
.content{{font-size:14px;white-space:pre-wrap}}
.toolname{{font-size:13px;font-weight:600;font-family:monospace}}
pre{{font-size:12px;background:#fff;border:1px solid #eee;padding:6px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-all}}
</style></head><body>
<h1>agent-milestone · 轨迹查看</h1>
{''.join(body)}
</body></html>"""

    if out_path is None:
        out_path = os.path.join(os.path.dirname(db_path), "trails.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_path


if __name__ == "__main__":
    p = render()
    print(f"已生成: {p}")
