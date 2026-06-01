from __future__ import annotations

from html import escape
from typing import Any

from service.takeoff_export import build_takeoff_rows


def build_job_report_html(
    *,
    job_id: str,
    status: str,
    created_at: str | None,
    updated_at: str | None,
    completed_at: str | None,
    input_payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
) -> str:
    """Build an estimator-friendly HTML report from a stored job result."""
    input_payload = input_payload if isinstance(input_payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    sheets = result.get("sheets_detected", [])
    sheets = sheets if isinstance(sheets, list) else []
    issues = result.get("issues_or_ambiguities", [])
    issues = issues if isinstance(issues, list) else []
    trade_scope = result.get("trade_scope", {})
    trade_scope = trade_scope if isinstance(trade_scope, dict) else {}
    analyzed_trades = trade_scope.get("analyzed_trades", [])
    if not isinstance(analyzed_trades, list):
        analyzed_trades = []
    rows = build_takeoff_rows(job_id=job_id, result=result)
    counts_rows = [row for row in rows if row.get("quantity_bucket") == "counts"]
    quantity_rows = [row for row in rows if row.get("quantity_bucket") != "cost_codes"]
    cost_code_rows = [row for row in rows if row.get("quantity_bucket") == "cost_codes"]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Estimator Report - {escape(job_id)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #071018;
      --panel: #101923;
      --panel-2: #142333;
      --line: #2C465D;
      --text: #EAF5FF;
      --muted: #9CB0BE;
      --accent: #FF8A00;
      --cyan: #1BD5FF;
      --danger: #FF4E64;
      --ok: #5DFF9D;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(255, 138, 0, 0.18), transparent 32rem),
        radial-gradient(circle at top right, rgba(27, 213, 255, 0.14), transparent 28rem),
        var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Aptos", sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 28px; }}
    header {{
      border: 1px solid var(--line);
      border-left: 6px solid var(--accent);
      border-radius: 18px;
      padding: 22px;
      background: linear-gradient(135deg, rgba(20, 35, 51, 0.96), rgba(9, 18, 28, 0.96));
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.32);
    }}
    h1, h2 {{ margin: 0; }}
    h1 {{ font-size: 2.1rem; letter-spacing: 0.02em; }}
    h2 {{ margin-bottom: 12px; font-size: 1.2rem; color: var(--cyan); }}
    .subtitle {{ color: var(--muted); margin-top: 6px; }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); margin-top: 18px; }}
    .card {{
      background: rgba(16, 25, 35, 0.9);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }}
    .label {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .value {{ font-size: 1.05rem; margin-top: 4px; overflow-wrap: anywhere; }}
    section {{ margin-top: 22px; background: rgba(16, 25, 35, 0.86); border: 1px solid var(--line); border-radius: 18px; padding: 18px; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 12px; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid rgba(44, 70, 93, 0.8); text-align: left; vertical-align: top; }}
    th {{ background: rgba(255, 138, 0, 0.12); color: #FFD9A8; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    tr:nth-child(even) td {{ background: rgba(255, 255, 255, 0.025); }}
    .empty {{ color: var(--muted); font-style: italic; }}
    .pill {{ display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 4px 9px; margin: 2px; background: var(--panel-2); }}
    .issue {{ border-left: 4px solid var(--danger); padding: 10px 12px; background: rgba(255, 78, 100, 0.08); margin: 8px 0; border-radius: 10px; }}
    .ok {{ color: var(--ok); }}
    .muted {{ color: var(--muted); }}
    @media print {{
      body {{ background: white; color: black; }}
      header, section {{ box-shadow: none; background: white; border-color: #bbb; }}
      th {{ color: black; background: #eee; }}
      .muted, .subtitle, .label {{ color: #444; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Estimator Report</h1>
      <div class="subtitle">Readable handoff summary generated from the structured job result.</div>
      <div class="grid">
        {_metric_card("Job ID", job_id)}
        {_metric_card("Status", status or "unknown")}
        {_metric_card("Sheets", str(len(sheets)))}
        {_metric_card("Analyzed Trades", str(len(analyzed_trades)))}
        {_metric_card("Quantity Rows", str(len(quantity_rows)))}
        {_metric_card("Count Rows", str(len(counts_rows)))}
      </div>
    </header>
    <section>
      <h2>Project Context</h2>
      <div class="grid">
        {_metric_card("Created", created_at or "")}
        {_metric_card("Updated", updated_at or "")}
        {_metric_card("Completed", completed_at or "")}
        {_metric_card("Analysis Mode", str(input_payload.get("analysis_mode", "")))}
        {_metric_card("Selected Trades", _join_list(input_payload.get("selected_trades")))}
        {_metric_card("Uploaded Files", str(len(input_payload.get("uploaded_files", []))) if isinstance(input_payload.get("uploaded_files"), list) else "0")}
      </div>
    </section>
    <section>
      <h2>Trade Scope</h2>
      {_trade_scope_html(trade_scope)}
    </section>
    <section>
      <h2>Quantity Takeoff</h2>
      {_quantity_table_html(quantity_rows[:500])}
    </section>
    <section>
      <h2>CSI Cost-Code Hints</h2>
      {_cost_code_table_html(cost_code_rows)}
    </section>
    <section>
      <h2>Sheets Detected</h2>
      {_sheets_table_html(sheets[:300])}
    </section>
    <section>
      <h2>Issues and Ambiguities</h2>
      {_issues_html(issues)}
    </section>
  </main>
</body>
</html>"""


def _metric_card(label: str, value: str) -> str:
    rendered_value = escape(value) if value else '<span class="muted">not provided</span>'
    return (
        '<div class="card">'
        f'<div class="label">{escape(label)}</div>'
        f'<div class="value">{rendered_value}</div>'
        "</div>"
    )


def _join_list(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _trade_scope_html(trade_scope: dict[str, Any]) -> str:
    if not trade_scope:
        return '<p class="empty">No trade scope data available.</p>'
    parts: list[str] = []
    for key in ("requested_mode", "detected_trades", "analyzed_trades", "skipped_trades"):
        value = trade_scope.get(key)
        if isinstance(value, list):
            rendered = "".join(f'<span class="pill">{escape(str(item))}</span>' for item in value) or '<span class="muted">none</span>'
        else:
            rendered = escape(str(value or ""))
        parts.append(f'<div class="card"><div class="label">{escape(key.replace("_", " ").title())}</div><div class="value">{rendered}</div></div>')
    return f'<div class="grid">{"".join(parts)}</div>'


def _quantity_table_html(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="empty">No quantity rows were available for this job.</p>'
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row.get('scope', ''))}</td>"
            f"<td>{escape(row.get('trade', '') or 'overall')}</td>"
            f"<td>{escape(row.get('quantity_bucket', ''))}</td>"
            f"<td>{escape(row.get('quantity_name', ''))}</td>"
            f"<td>{escape(row.get('value', ''))}</td>"
            f"<td>{escape(row.get('unit_hint', ''))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Scope</th><th>Trade</th><th>Bucket</th><th>Quantity</th><th>Value</th><th>Unit</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _cost_code_table_html(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="empty">No CSI cost-code hints were available for this job.</p>'
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row.get('trade', ''))}</td>"
            f"<td>{escape(row.get('quantity_name', ''))}</td>"
            f"<td>{escape(row.get('value', ''))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Trade</th><th>Code Set</th><th>Codes</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def _sheets_table_html(sheets: list[object]) -> str:
    if not sheets:
        return '<p class="empty">No sheet rows were detected.</p>'
    body = []
    for item in sheets:
        row = item if isinstance(item, dict) else {}
        body.append(
            "<tr>"
            f"<td>{escape(str(row.get('source_page_index', '')))}</td>"
            f"<td>{escape(str(row.get('sheet_id', '')))}</td>"
            f"<td>{escape(str(row.get('title', '')))}</td>"
            f"<td>{escape(str(row.get('discipline', '')))}</td>"
            f"<td>{escape(str(row.get('sheet_type', '')))}</td>"
            f"<td>{escape(str(row.get('confidence', '')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Page</th><th>Sheet ID</th><th>Title</th><th>Trade</th><th>Sheet Type</th><th>Confidence</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _issues_html(issues: list[object]) -> str:
    if not issues:
        return '<p class="ok">No issues or ambiguities were reported.</p>'
    body = []
    for item in issues:
        if isinstance(item, dict):
            message = str(item.get("message", item))
            severity = str(item.get("severity", "warning"))
        else:
            message = str(item)
            severity = "warning"
        body.append(
            f'<div class="issue"><strong>{escape(severity.title())}</strong><br>{escape(message)}</div>'
        )
    return "".join(body)
