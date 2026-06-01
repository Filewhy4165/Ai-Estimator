from __future__ import annotations

from copy import deepcopy
from html import escape
from typing import Any

from ai_estimator.extractors.takeoff import compute_quantity_takeoff


DEFAULT_SVG_WIDTH = 1000.0
DEFAULT_SVG_HEIGHT = 750.0
MAX_SVG_EVIDENCE_ITEMS = 2000


def build_visual_evidence_svg(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    sheet_id: str | None = None,
    source_page_index: int | None = None,
    limit: int = 500,
) -> str:
    """Render one sheet/page of extracted PDF vector evidence as an SVG overlay."""
    result = result or {}
    annotations = _extract_annotations(result)
    pages = _dict_rows(annotations.get("vector_pages", []))
    evidence = _dict_rows(annotations.get("vector_evidence", []))

    selected_page = _select_page(
        pages=pages,
        evidence=evidence,
        sheet_id=sheet_id,
        source_page_index=source_page_index,
    )
    selected_sheet_id = str(selected_page.get("sheet_id", sheet_id or "unknown")).strip() or "unknown"
    selected_source_page = _parse_positive_int(
        selected_page.get("source_page_index", source_page_index)
    )
    width = _positive_float(selected_page.get("page_width_pdf_units")) or DEFAULT_SVG_WIDTH
    height = _positive_float(selected_page.get("page_height_pdf_units")) or DEFAULT_SVG_HEIGHT

    normalized_limit = max(1, min(int(limit or 500), MAX_SVG_EVIDENCE_ITEMS))
    selected_evidence = [
        row
        for row in evidence
        if _matches_sheet_page(row, selected_sheet_id, selected_source_page)
    ][:normalized_limit]

    if not selected_evidence:
        selected_evidence = [
            row
            for row in evidence
            if (not sheet_id or str(row.get("sheet_id", "")).strip() == str(sheet_id).strip())
            and (
                source_page_index is None
                or _parse_positive_int(row.get("source_page_index")) == source_page_index
            )
        ][:normalized_limit]

    primitives = "\n".join(_primitive_to_svg(row, height) for row in selected_evidence)
    label = (
        f"Job {job_id} | Sheet {selected_sheet_id} | "
        f"Page {selected_source_page or 'unknown'} | Evidence {len(selected_evidence)}"
    )

    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
                f'viewBox="0 0 {width:.4f} {height:.4f}" '
                f'width="{width:.4f}" height="{height:.4f}" '
                f'data-job-id="{escape(job_id)}" '
                f'data-sheet-id="{escape(selected_sheet_id)}" '
                f'data-source-page-index="{selected_source_page or ""}">'
            ),
            "<defs>",
            (
                '<pattern id="minor-grid" width="25" height="25" patternUnits="userSpaceOnUse">'
                '<path d="M 25 0 L 0 0 0 25" fill="none" stroke="#1e3a46" stroke-width="0.45"/>'
                "</pattern>"
            ),
            (
                '<pattern id="major-grid" width="100" height="100" patternUnits="userSpaceOnUse">'
                '<rect width="100" height="100" fill="url(#minor-grid)"/>'
                '<path d="M 100 0 L 0 0 0 100" fill="none" stroke="#2d5f70" stroke-width="0.9"/>'
                "</pattern>"
            ),
            "</defs>",
            f'<rect x="0" y="0" width="{width:.4f}" height="{height:.4f}" fill="#071113"/>',
            f'<rect x="0" y="0" width="{width:.4f}" height="{height:.4f}" fill="url(#major-grid)" opacity="0.55"/>',
            (
                f'<rect x="1.5" y="1.5" width="{max(width - 3, 1):.4f}" '
                f'height="{max(height - 3, 1):.4f}" fill="none" stroke="#ffb02e" '
                'stroke-width="3" opacity="0.85"/>'
            ),
            primitives,
            (
                '<rect x="14" y="14" width="680" height="42" rx="8" '
                'fill="#081923" stroke="#34d3ff" stroke-width="1.5" opacity="0.9"/>'
            ),
            (
                f'<text x="28" y="41" fill="#f4fbff" font-family="Segoe UI, Arial, sans-serif" '
                f'font-size="18" font-weight="700">{escape(label)}</text>'
            ),
            "</svg>",
        ]
    )


def build_visual_measurement_page(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    sheet_id: str | None = None,
    source_page_index: int | None = None,
    tenant_id: str = "",
    limit: int = 500,
) -> str:
    """Render an interactive browser page for click-based scale measurement."""
    svg = build_visual_evidence_svg(
        job_id=job_id,
        result=result,
        sheet_id=sheet_id,
        source_page_index=source_page_index,
        limit=limit,
    )
    selected_sheet = _extract_svg_attr(svg, "data-sheet-id") or str(sheet_id or "").strip()
    selected_page = _extract_svg_attr(svg, "data-source-page-index")
    tenant_value = str(tenant_id or "").strip()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EstimateForge Visual Measurement</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%2305070d'/%3E%3Cpath d='M14 46 L28 12 H50 L44 24 H30 L27 31 H42 L36 43 H23 L20 52 H10 Z' fill='%23dbeafe'/%3E%3Cpath d='M8 34 H56' stroke='%23ff3b4f' stroke-width='5'/%3E%3C/svg%3E" />
  <style>
    :root {{
      --bg: #05070d;
      --panel: #10151d;
      --panel-2: #151c26;
      --text: #f8fafc;
      --muted: #9fb3c8;
      --cyan: #19e6ff;
      --amber: #ffb000;
      --orange: #ff5a1f;
      --danger: #ff3b4f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #112637, var(--bg) 42%);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    header {{
      padding: 18px 24px;
      border-bottom: 1px solid #263244;
      background: linear-gradient(90deg, #0a111b, #141f2c);
      box-shadow: 0 8px 26px rgba(0, 0, 0, 0.32);
    }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.02em; }}
    header p {{ margin: 6px 0 0; color: var(--muted); }}
    main {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 390px;
      gap: 16px;
      padding: 16px;
      height: calc(100vh - 82px);
    }}
    .viewer, .tools {{
      min-height: 0;
      border: 1px solid #29384c;
      border-radius: 14px;
      background: rgba(16, 21, 29, 0.92);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 14px 40px rgba(0,0,0,0.30);
    }}
    .viewer {{
      overflow: auto;
      padding: 12px;
      position: relative;
    }}
    .viewer svg {{
      min-width: 960px;
      max-width: none;
      height: auto;
      cursor: crosshair;
      border-radius: 10px;
      box-shadow: 0 0 0 1px rgba(25, 230, 255, 0.28), 0 0 38px rgba(25, 230, 255, 0.12);
    }}
    .tools {{
      overflow: auto;
      padding: 16px;
    }}
    .section {{
      padding: 14px;
      margin-bottom: 14px;
      border: 1px solid #263244;
      border-radius: 12px;
      background: linear-gradient(180deg, var(--panel-2), var(--panel));
    }}
    .section h2 {{
      margin: 0 0 10px;
      font-size: 15px;
      color: var(--cyan);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    label {{
      display: block;
      margin: 10px 0 5px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    input {{
      width: 100%;
      padding: 10px 11px;
      border: 1px solid #334155;
      border-radius: 9px;
      background: #071018;
      color: var(--text);
      font-size: 14px;
    }}
    button {{
      width: 100%;
      margin-top: 10px;
      padding: 11px 12px;
      border: 1px solid #345065;
      border-radius: 10px;
      background: linear-gradient(180deg, #203142, #121d29);
      color: var(--text);
      font-weight: 800;
      cursor: pointer;
      box-shadow: inset 0 1px rgba(255,255,255,0.08), 0 4px 0 #070b10;
    }}
    button.primary {{ border-color: var(--cyan); color: #041016; background: linear-gradient(180deg, #62f1ff, var(--cyan)); }}
    button.apply {{ border-color: var(--amber); color: #101010; background: linear-gradient(180deg, #ffd073, var(--amber)); }}
    button:hover {{ filter: brightness(1.08); }}
    .metric {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid #223044;
      color: var(--muted);
    }}
    .metric strong {{ color: var(--text); text-align: right; }}
    .hint {{ color: var(--muted); font-size: 13px; line-height: 1.42; }}
    .status {{
      white-space: pre-wrap;
      color: var(--text);
      background: #071018;
      border: 1px solid #263244;
      border-radius: 10px;
      padding: 10px;
      min-height: 84px;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 12px;
    }}
    .measure-line {{ stroke: var(--danger); stroke-width: 3; stroke-dasharray: 9 6; pointer-events: none; }}
    .measure-point {{ fill: var(--danger); stroke: #fff; stroke-width: 2; pointer-events: none; }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns: 1fr; height: auto; }}
      .viewer {{ height: 62vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>EstimateForge Visual Measurement</h1>
    <p>Click two points on a known drawing dimension, enter the real length, then preview or apply scale.</p>
  </header>
  <main>
    <section class="viewer" id="viewer">
      {svg}
    </section>
    <aside class="tools">
      <div class="section">
        <h2>Selected Sheet</h2>
        <div class="metric"><span>Job</span><strong id="jobId">{escape(job_id)}</strong></div>
        <div class="metric"><span>Sheet</span><strong id="sheetId">{escape(selected_sheet)}</strong></div>
        <div class="metric"><span>Page</span><strong id="pageIndex">{escape(selected_page or "-")}</strong></div>
        <label for="tenantId">Company Workspace</label>
        <input id="tenantId" value="{escape(tenant_value)}" placeholder="default" />
        <label for="apiKey">Security Key (optional)</label>
        <input id="apiKey" type="password" placeholder="Only needed if the server requires one" />
      </div>
      <div class="section">
        <h2>Measure Known Length</h2>
        <p class="hint">Click point A and point B on the drawing. The measured PDF units will fill automatically.</p>
        <label for="pointA">Point A</label>
        <input id="pointA" readonly />
        <label for="pointB">Point B</label>
        <input id="pointB" readonly />
        <label for="measuredPdfUnits">Measured PDF Units</label>
        <input id="measuredPdfUnits" />
        <label for="knownLengthFt">Known Real Length (feet)</label>
        <input id="knownLengthFt" placeholder="Example: 24" />
        <button type="button" id="resetBtn">Reset Clicks</button>
        <button type="button" class="primary" id="previewBtn">Preview Scale</button>
        <button type="button" class="apply" id="applyBtn">Apply Scale to Job Result</button>
      </div>
      <div class="section">
        <h2>Result</h2>
        <div class="status" id="status">Ready. Click two points on the drawing.</div>
      </div>
    </aside>
  </main>
  <script>
    const svg = document.querySelector(".viewer svg");
    const statusBox = document.getElementById("status");
    const pointAInput = document.getElementById("pointA");
    const pointBInput = document.getElementById("pointB");
    const measuredInput = document.getElementById("measuredPdfUnits");
    const knownInput = document.getElementById("knownLengthFt");
    const tenantInput = document.getElementById("tenantId");
    const apiKeyInput = document.getElementById("apiKey");
    const sheetId = document.getElementById("sheetId").textContent.trim();
    const jobId = document.getElementById("jobId").textContent.trim();
    let points = [];
    let overlayGroup = null;

    function setStatus(value) {{
      statusBox.textContent = value;
    }}

    function headers() {{
      const h = {{}};
      const tenant = tenantInput.value.trim();
      const apiKey = apiKeyInput.value.trim();
      if (tenant) h["x-tenant-id"] = tenant;
      if (apiKey) h["x-api-key"] = apiKey;
      return h;
    }}

    function svgPointFromEvent(event) {{
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const transformed = point.matrixTransform(svg.getScreenCTM().inverse());
      return {{ x: transformed.x, y: transformed.y }};
    }}

    function distance(a, b) {{
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      return Math.sqrt(dx * dx + dy * dy);
    }}

    function formatPoint(p) {{
      return `${{p.x.toFixed(3)}}, ${{p.y.toFixed(3)}}`;
    }}

    function resetOverlay() {{
      if (overlayGroup) overlayGroup.remove();
      overlayGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
      overlayGroup.setAttribute("id", "measurement-overlay");
      svg.appendChild(overlayGroup);
    }}

    function drawMeasurement() {{
      resetOverlay();
      for (const p of points) {{
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("class", "measure-point");
        c.setAttribute("cx", p.x);
        c.setAttribute("cy", p.y);
        c.setAttribute("r", "7");
        overlayGroup.appendChild(c);
      }}
      if (points.length === 2) {{
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("class", "measure-line");
        line.setAttribute("x1", points[0].x);
        line.setAttribute("y1", points[0].y);
        line.setAttribute("x2", points[1].x);
        line.setAttribute("y2", points[1].y);
        overlayGroup.insertBefore(line, overlayGroup.firstChild);
      }}
    }}

    function resetClicks() {{
      points = [];
      pointAInput.value = "";
      pointBInput.value = "";
      measuredInput.value = "";
      resetOverlay();
      setStatus("Ready. Click two points on the drawing.");
    }}

    svg.addEventListener("click", (event) => {{
      const p = svgPointFromEvent(event);
      if (points.length >= 2) points = [];
      points.push(p);
      if (points[0]) pointAInput.value = formatPoint(points[0]);
      if (points[1]) pointBInput.value = formatPoint(points[1]);
      if (points.length === 2) {{
        const d = distance(points[0], points[1]);
        measuredInput.value = d.toFixed(6);
        setStatus(`Measured ${{d.toFixed(4)}} PDF units. Enter known real length in feet.`);
      }} else {{
        setStatus("Point A set. Click point B.");
      }}
      drawMeasurement();
    }});

    async function callCalibration(method, endpoint) {{
      const measured = Number(measuredInput.value);
      const known = Number(knownInput.value);
      if (!Number.isFinite(measured) || measured <= 0) {{
        throw new Error("Measured PDF Units must be greater than 0.");
      }}
      if (!Number.isFinite(known) || known <= 0) {{
        throw new Error("Known Real Length must be greater than 0.");
      }}
      const params = new URLSearchParams({{
        sheet_id: sheetId,
        measured_pdf_units: String(measured),
        known_length_ft: String(known),
      }});
      const response = await fetch(`${{endpoint}}?${{params.toString()}}`, {{
        method,
        headers: headers(),
      }});
      const text = await response.text();
      let payload;
      try {{
        payload = JSON.parse(text);
      }} catch (_err) {{
        throw new Error(text || "Server did not return JSON.");
      }}
      if (!response.ok) {{
        throw new Error(payload.detail || text || `HTTP ${{response.status}}`);
      }}
      return payload;
    }}

    document.getElementById("resetBtn").addEventListener("click", resetClicks);
    document.getElementById("previewBtn").addEventListener("click", async () => {{
      try {{
        setStatus("Previewing scale...");
        const payload = await callCalibration("GET", `/v1/jobs/${{encodeURIComponent(jobId)}}/scale-calibration/preview`);
        const c = payload.calibration || {{}};
        const p = payload.preview || {{}};
        setStatus(
          `Preview complete.\\n` +
          `Feet per PDF unit: ${{c.feet_per_pdf_unit}}\\n` +
          `PDF units per foot: ${{c.pdf_units_per_foot}}\\n` +
          `Calibrated vector linework: ${{p.calibrated_vector_linework_total_ft}} ft`
        );
      }} catch (err) {{
        setStatus(`Preview failed:\\n${{err.message}}`);
      }}
    }});
    document.getElementById("applyBtn").addEventListener("click", async () => {{
      try {{
        setStatus("Applying scale to job result...");
        const payload = await callCalibration("POST", `/v1/jobs/${{encodeURIComponent(jobId)}}/scale-calibration/apply`);
        const c = payload.calibration || {{}};
        const p = payload.preview || {{}};
        setStatus(
          `Scale applied to job result.\\n` +
          `Feet per PDF unit: ${{c.feet_per_pdf_unit}}\\n` +
          `Updated linework: ${{p.calibrated_vector_linework_total_ft}} ft\\n` +
          `Refresh the desktop job to see the updated takeoff.`
        );
      }} catch (err) {{
        setStatus(`Apply failed:\\n${{err.message}}`);
      }}
    }});
    resetOverlay();
  </script>
</body>
</html>"""


def build_scale_calibration_preview(
    *,
    job_id: str,
    result: dict[str, Any] | None,
    sheet_id: str,
    measured_pdf_units: float,
    known_length_ft: float,
) -> dict[str, Any]:
    """Preview a sheet-level feet-per-PDF-unit calibration from one known length."""
    normalized_sheet_id = str(sheet_id or "").strip()
    if not normalized_sheet_id:
        raise ValueError("sheet_id is required.")
    measured = _positive_float(measured_pdf_units)
    known = _positive_float(known_length_ft)
    if measured is None:
        raise ValueError("measured_pdf_units must be greater than 0.")
    if known is None:
        raise ValueError("known_length_ft must be greater than 0.")

    feet_per_pdf_unit = known / measured
    result = result or {}
    annotations = _extract_annotations(result)
    measurements = [
        row
        for row in _dict_rows(annotations.get("vector_measurements", []))
        if str(row.get("sheet_id", "")).strip() == normalized_sheet_id
    ]

    total_pdf_units = sum(_to_float(row.get("total_linework_pdf_units")) for row in measurements)
    line_pdf_units = sum(_to_float(row.get("line_length_pdf_units")) for row in measurements)
    rectangle_pdf_units = sum(
        _to_float(row.get("rectangle_perimeter_pdf_units")) for row in measurements
    )
    primitive_count = sum(
        int(_to_float(row.get("line_count")) + _to_float(row.get("rectangle_count")))
        for row in measurements
    )
    source_pages = sorted(
        {
            page
            for page in (_parse_positive_int(row.get("source_page_index")) for row in measurements)
            if page is not None
        }
    )

    warnings: list[str] = []
    if not measurements:
        warnings.append("No vector measurements were found for this sheet.")
    if total_pdf_units <= 0:
        warnings.append("No positive vector linework length was found for this sheet.")

    return {
        "job_id": job_id,
        "sheet_id": normalized_sheet_id,
        "calibration": {
            "known_length_ft": round(known, 6),
            "measured_pdf_units": round(measured, 6),
            "feet_per_pdf_unit": round(feet_per_pdf_unit, 10),
            "pdf_units_per_foot": round(measured / known, 10),
        },
        "preview": {
            "vector_measurement_count": len(measurements),
            "primitive_count": primitive_count,
            "source_page_indexes": source_pages,
            "line_length_pdf_units": round(line_pdf_units, 4),
            "rectangle_perimeter_pdf_units": round(rectangle_pdf_units, 4),
            "total_linework_pdf_units": round(total_pdf_units, 4),
            "calibrated_line_length_ft": round(line_pdf_units * feet_per_pdf_unit, 4),
            "calibrated_rectangle_perimeter_ft": round(rectangle_pdf_units * feet_per_pdf_unit, 4),
            "calibrated_vector_linework_total_ft": round(total_pdf_units * feet_per_pdf_unit, 4),
        },
        "warnings": warnings,
        "note": (
            "Preview only. This does not modify stored job results; use it to confirm "
            "a known drawing dimension before persistent calibration is applied."
        ),
    }


def apply_scale_calibration_to_result(
    *,
    result: dict[str, Any] | None,
    sheet_id: str,
    measured_pdf_units: float,
    known_length_ft: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a result copy with a manual sheet scale calibration applied."""
    preview = build_scale_calibration_preview(
        job_id="calibration-preview",
        result=result,
        sheet_id=sheet_id,
        measured_pdf_units=measured_pdf_units,
        known_length_ft=known_length_ft,
    )
    updated_result: dict[str, Any] = deepcopy(result or {})
    if not updated_result:
        raise ValueError("Completed job result is required before applying calibration.")

    geometry = updated_result.get("geometry", {})
    if not isinstance(geometry, dict):
        raise ValueError("Completed job result does not contain geometry.")

    scale_analysis = updated_result.get("scale_analysis")
    if not isinstance(scale_analysis, dict):
        scale_analysis = {}
        updated_result["scale_analysis"] = scale_analysis

    rows = scale_analysis.get("by_sheet", [])
    if not isinstance(rows, list):
        rows = []
    normalized_sheet_id = str(sheet_id).strip()
    rows = [
        row
        for row in rows
        if not (
            isinstance(row, dict)
            and str(row.get("sheet_id", "")).strip() == normalized_sheet_id
            and str(row.get("scale_source", "")).strip() == "manual_calibration"
        )
    ]

    calibration = preview["calibration"]
    manual_row = {
        "sheet_id": normalized_sheet_id,
        "detected_scale": "manual calibration",
        "units": "manual",
        "confidence": 1.0,
        "scale_source": "manual_calibration",
        "known_length_ft": calibration["known_length_ft"],
        "measured_pdf_units": calibration["measured_pdf_units"],
        "feet_per_pdf_unit": calibration["feet_per_pdf_unit"],
        "pdf_units_per_foot": calibration["pdf_units_per_foot"],
    }
    rows.append(manual_row)
    scale_analysis["by_sheet"] = rows

    manual_calibrations = scale_analysis.get("manual_calibrations", [])
    if not isinstance(manual_calibrations, list):
        manual_calibrations = []
    manual_calibrations = [
        row
        for row in manual_calibrations
        if not (isinstance(row, dict) and str(row.get("sheet_id", "")).strip() == normalized_sheet_id)
    ]
    manual_calibrations.append(manual_row)
    scale_analysis["manual_calibrations"] = manual_calibrations

    quantity_takeoff, takeoff_issues = compute_quantity_takeoff(
        geometry,
        scale_analysis=scale_analysis,
    )
    updated_result["quantity_takeoff"] = quantity_takeoff

    issue_message = (
        f"Manual scale calibration applied for sheet {normalized_sheet_id}: "
        f"{calibration['known_length_ft']} ft over {calibration['measured_pdf_units']} PDF units."
    )
    issues = updated_result.get("issues_or_ambiguities", [])
    if not isinstance(issues, list):
        issues = []
    merged_issues = [str(item) if not isinstance(item, dict) else item for item in issues]
    if issue_message not in [str(item) for item in merged_issues]:
        merged_issues.append(issue_message)
    for issue in takeoff_issues:
        if issue not in [str(item) for item in merged_issues]:
            merged_issues.append(issue)
    updated_result["issues_or_ambiguities"] = merged_issues

    apply_payload = {
        "applied": True,
        "sheet_id": normalized_sheet_id,
        "calibration": calibration,
        "preview": preview["preview"],
        "quantity_takeoff": quantity_takeoff,
        "warnings": preview.get("warnings", []),
        "note": "Manual scale calibration was applied to the stored job result.",
    }
    return updated_result, apply_payload


def _extract_annotations(result: dict[str, Any]) -> dict[str, Any]:
    geometry = result.get("geometry", {})
    if not isinstance(geometry, dict):
        return {}
    annotations = geometry.get("annotations", {})
    return annotations if isinstance(annotations, dict) else {}


def _extract_svg_attr(svg: str, attr_name: str) -> str:
    marker = f'{attr_name}="'
    start = svg.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = svg.find('"', start)
    if end < 0:
        return ""
    return svg[start:end]


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _select_page(
    *,
    pages: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    sheet_id: str | None,
    source_page_index: int | None,
) -> dict[str, Any]:
    normalized_sheet_id = str(sheet_id or "").strip()
    for page in sorted(pages, key=_page_sort_key):
        if normalized_sheet_id and str(page.get("sheet_id", "")).strip() != normalized_sheet_id:
            continue
        if source_page_index is not None and _parse_positive_int(page.get("source_page_index")) != source_page_index:
            continue
        return page

    for row in evidence:
        if normalized_sheet_id and str(row.get("sheet_id", "")).strip() != normalized_sheet_id:
            continue
        if source_page_index is not None and _parse_positive_int(row.get("source_page_index")) != source_page_index:
            continue
        return {
            "sheet_id": str(row.get("sheet_id", normalized_sheet_id or "unknown")).strip() or "unknown",
            "source_page_index": _parse_positive_int(row.get("source_page_index", source_page_index)),
            "page_width_pdf_units": _max_point_value(row, axis=0) or DEFAULT_SVG_WIDTH,
            "page_height_pdf_units": _max_point_value(row, axis=1) or DEFAULT_SVG_HEIGHT,
        }

    return {
        "sheet_id": normalized_sheet_id or "unknown",
        "source_page_index": source_page_index,
        "page_width_pdf_units": DEFAULT_SVG_WIDTH,
        "page_height_pdf_units": DEFAULT_SVG_HEIGHT,
    }


def _matches_sheet_page(row: dict[str, Any], sheet_id: str, source_page_index: int | None) -> bool:
    if str(row.get("sheet_id", "")).strip() != sheet_id:
        return False
    if source_page_index is None:
        return True
    return _parse_positive_int(row.get("source_page_index")) == source_page_index


def _primitive_to_svg(row: dict[str, Any], page_height: float) -> str:
    points = _extract_points(row)
    if len(points) < 2:
        return ""

    kind = str(row.get("kind", "")).strip().lower()
    color = "#34d3ff" if kind == "line" else "#ffb02e"
    stroke_width = max(_to_float(row.get("line_width")), 1.4)
    svg_points = " ".join(f"{x:.4f},{page_height - y:.4f}" for x, y in points)
    common = (
        f'stroke="{color}" stroke-width="{stroke_width:.4f}" '
        'stroke-linecap="round" stroke-linejoin="round" opacity="0.82"'
    )
    if kind == "rectangle" and len(points) >= 4:
        return f'<polygon points="{svg_points}" fill="none" {common}/>'
    return f'<polyline points="{svg_points}" fill="none" {common}/>'


def _extract_points(row: dict[str, Any]) -> list[tuple[float, float]]:
    raw_points = row.get("points", [])
    points: list[tuple[float, float]] = []
    if isinstance(raw_points, list):
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            x = _to_float(point[0])
            y = _to_float(point[1])
            points.append((x, y))
    if points:
        return points

    bbox = row.get("bbox", [])
    if isinstance(bbox, list) and len(bbox) >= 4:
        x1, y1, x2, y2 = (_to_float(value) for value in bbox[:4])
        if x1 != x2 or y1 != y2:
            return [(x1, y1), (x2, y2)]
    return []


def _max_point_value(row: dict[str, Any], *, axis: int) -> float | None:
    points = _extract_points(row)
    if not points:
        return None
    return max(point[axis] for point in points) + 25.0


def _page_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    page = _parse_positive_int(row.get("source_page_index"))
    return (page if page is not None else 999999, str(row.get("sheet_id", "")))


def _parse_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _positive_float(value: Any) -> float | None:
    parsed = _to_float(value)
    return parsed if parsed > 0 else None


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0
