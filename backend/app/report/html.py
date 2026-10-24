"""单文件 HTML 报告：面试官点不开本地 demo，就给他一个能双击打开的页面（§14）。"""

from __future__ import annotations

import html as htmllib
from typing import Any

STYLE = """
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:860px;margin:40px auto;padding:0 20px;color:#1f2328;line-height:1.7}
h1{font-size:24px;margin-bottom:8px}
h2{font-size:16px;margin:32px 0 12px;padding-bottom:6px;border-bottom:1px solid #e5e7eb}
.meta{color:#6b7280;font-size:13px}
.card{border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:12px 0}
.cover{display:inline-block;background:#fff1f2;color:#be123c;border-radius:6px;padding:6px 10px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left}
th{background:#f9fafb;font-weight:600}
.tag{display:inline-block;background:#eef2ff;color:#4338ca;border-radius:4px;padding:2px 8px;margin-right:6px;font-size:13px}
.score{font-size:28px;font-weight:700}
.arrow{color:#9ca3af;margin:0 10px}
.ok{color:#047857}.bad{color:#b91c1c}
mark{background:#fef08a;padding:0 2px}
"""


def _esc(value: Any) -> str:
    return htmllib.escape("" if value is None else str(value))


def _paragraphs(body: str | None) -> str:
    if not body:
        return "<p class='meta'>（没有正文）</p>"
    return "".join(f"<p>{_esc(block)}</p>" for block in body.split("\n\n") if block.strip())


def _rounds_table(events: list[dict[str, Any]]) -> str:
    rows = []
    for event in events:
        if event.get("event") != "round":
            continue
        verdict = event.get("verdict") or {}
        rows.append(
            "<tr><td>第 {round} 轮</td><td>{click}</td><td>{save}</td><td>{read}</td><td>{drop}</td></tr>".format(
                round=event.get("round"),
                click="是" if verdict.get("click") else "否",
                save="是" if verdict.get("save") else "否",
                read=f"{verdict.get('read_through', 0):.0%}",
                drop=verdict.get("drop_at_sentence") or "看完",
            )
        )
    if not rows:
        return "<p class='meta'>（没有判定卡）</p>"
    return (
        "<table><thead><tr><th>轮次</th><th>会点开</th><th>会收藏</th>"
        "<th>读完</th><th>第几句划走</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _smell_block(meta: dict[str, Any]) -> str:
    smell = meta.get("smell") or {}
    before = smell.get("before", "—")
    after = smell.get("after", "—")
    fidelity = smell.get("fidelity", "—")
    return (
        "<div class='card'>"
        f"<span class='score'>{_esc(before)}</span><span class='arrow'>→</span>"
        f"<span class='score'>{_esc(after)}</span>"
        f"<div class='meta'>AI 味分数（越低越像人写的）｜保真校验：{_esc(fidelity)}｜"
        f"改动 {_esc(meta.get('changes', 0))} 处</div></div>"
    )


def _gate_block(meta: dict[str, Any]) -> str:
    findings = meta.get("gate_findings") or []
    if not findings:
        return "<p class='ok'>守门人：无命中</p>"
    rows = []
    for finding in findings:
        verdict = "误报，放行" if finding.get("false_positive") else "命中"
        cls = "ok" if finding.get("false_positive") else "bad"
        rows.append(
            f"<tr><td>{_esc(finding.get('rule_id'))}</td><td><mark>{_esc(finding.get('matched'))}</mark></td>"
            f"<td>{_esc(finding.get('severity'))}</td><td class='{cls}'>{verdict}</td>"
            f"<td>{_esc(finding.get('hint'))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>规则</th><th>命中</th><th>级别</th><th>结论</th><th>建议</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_report(events: list[dict[str, Any]], result: dict[str, Any]) -> str:
    meta = result.get("meta") or {}
    usage = meta.get("usage") or {}
    tags = "".join(f"<span class='tag'>{_esc(tag)}</span>" for tag in (result.get("tags") or []))
    failed = meta.get("failed_checks") or []
    failed_html = (
        "<ul>" + "".join(f"<li>{_esc(item.get('label'))}：{_esc(item.get('detail'))}</li>" for item in failed) + "</ul>"
        if failed
        else "<p class='ok'>没有未达标项</p>"
    )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>小红书多角色生成 · 过程报告</title>
<style>{STYLE}</style></head>
<body>
<h1>{_esc(result.get("title") or "（没有标题）")}</h1>
<div class="meta">状态：{_esc(result.get("status"))}　轮次：{_esc(meta.get("rounds_used", 0))}
　交付第 {_esc(meta.get("best_round") or "—")} 轮　成本：{_esc(usage.get("cost_cny", 0))} 元
　耗时：{_esc(usage.get("elapsed_s", 0))} 秒　调用：{_esc(usage.get("calls", 0))} 次</div>

<h2>封面文案</h2>
<div class="cover">{_esc(result.get("cover_text") or "—")}</div>

<h2>正文</h2>
<div class="card">{_paragraphs(result.get("body"))}</div>
<div>{tags}</div>

<h2>AI 味清理</h2>
{_smell_block(meta)}

<h2>读者判定</h2>
{_rounds_table(events)}

<h2>未达标项</h2>
{failed_html}

<h2>守门人</h2>
{_gate_block(meta)}

<h2>用量</h2>
<div class="meta">输入 {_esc(usage.get("input_tokens", 0))} tokens｜
输出 {_esc(usage.get("output_tokens", 0))} tokens｜
合计 {_esc(usage.get("cost_cny", 0))} 元</div>
</body></html>
"""
