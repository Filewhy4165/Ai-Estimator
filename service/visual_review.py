from __future__ import annotations

from copy import deepcopy
from html import escape
import json
from typing import Any

from ai_estimator.extractors.takeoff import compute_quantity_takeoff


DEFAULT_SVG_WIDTH = 1000.0
DEFAULT_SVG_HEIGHT = 750.0
MAX_SVG_EVIDENCE_ITEMS = 2000
MAX_VISUAL_MEASUREMENTS = 500


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
    display_label = _truncate_text(label, 86)

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
                f'font-size="18" font-weight="700">{escape(display_label)}</text>'
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
    selected_page_index = _parse_positive_int(selected_page)
    saved_measurements = list_visual_measurements(
        result=result,
        sheet_id=selected_sheet,
        source_page_index=selected_page_index,
    )
    saved_measurements_json = _script_json(saved_measurements)
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
    html, body {{ height: 100%; overflow: hidden; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #112637, var(--bg) 42%);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      flex: 0 0 auto;
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
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
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
      min-width: 0;
    }}
    .viewer-toolbar {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin: 0 0 10px;
      padding: 8px;
      border: 1px solid #29384c;
      border-radius: 10px;
      background: rgba(7, 16, 24, 0.94);
      box-shadow: 0 10px 26px rgba(0, 0, 0, 0.28);
    }}
    .viewer-toolbar button {{
      width: auto;
      min-width: 86px;
      margin: 0;
      padding: 8px 10px;
      font-size: 12px;
    }}
    .viewer-toolbar span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-left: auto;
    }}
    .viewer svg {{
      display: block;
      width: auto;
      max-width: 100%;
      max-height: none;
      height: auto;
      cursor: crosshair;
      border-radius: 10px;
      box-shadow: 0 0 0 1px rgba(25, 230, 255, 0.28), 0 0 38px rgba(25, 230, 255, 0.12);
    }}
    .tools {{
      overflow: auto;
      padding: 16px;
      min-height: 0;
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
    input, select {{
      width: 100%;
      padding: 10px 11px;
      border: 1px solid #334155;
      border-radius: 9px;
      background: #071018;
      color: var(--text);
      font-size: 14px;
    }}
    .check-row {{
      display: flex;
      align-items: center;
      gap: 9px;
      margin-top: 12px;
      padding: 10px;
      border: 1px solid #2e4056;
      border-radius: 10px;
      background: rgba(7, 16, 24, 0.74);
      color: var(--text);
      cursor: pointer;
    }}
    .check-row input {{
      width: auto;
      accent-color: var(--cyan);
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
    button.danger {{ border-color: var(--danger); background: linear-gradient(180deg, #5d1c28, #251018); }}
    .button-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}
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
    .measurement-list {{
      display: grid;
      gap: 8px;
      max-height: 210px;
      overflow: auto;
      padding-right: 2px;
    }}
    .measurement-summary {{
      margin-top: 10px;
      padding: 8px 10px;
      border: 1px solid #263244;
      border-radius: 10px;
      background: rgba(7, 16, 24, 0.58);
    }}
    .measurement-card {{
      width: 100%;
      margin: 0;
      text-align: left;
      border-color: #2b4058;
      box-shadow: inset 0 1px rgba(255,255,255,0.08), 0 2px 0 #070b10;
    }}
    .measurement-card.active {{
      border-color: var(--cyan);
      background: linear-gradient(180deg, #203d48, #102430);
    }}
    .measurement-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      color: var(--text);
    }}
    .measurement-meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
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
    .measure-line {{ stroke: #ff6b7a; stroke-width: 3; stroke-dasharray: 9 6; pointer-events: none; }}
    .measure-line.active {{ stroke: var(--danger); stroke-width: 4; }}
    .measure-point {{ fill: var(--danger); stroke: #fff; stroke-width: 2; pointer-events: all; cursor: grab; }}
    .measure-point.inactive {{ fill: #ffc24a; }}
    .measure-point:active {{ cursor: grabbing; }}
    .measure-label {{
      fill: #ffffff;
      font: 700 13px "Segoe UI", Arial, sans-serif;
      paint-order: stroke;
      stroke: #071018;
      stroke-width: 4px;
      pointer-events: none;
    }}
    @media (max-width: 980px) {{
      html, body {{ height: auto; overflow: auto; }}
      body {{ min-height: 100dvh; }}
      main {{ grid-template-columns: 1fr; overflow: visible; }}
      .viewer {{ height: 62vh; }}
      .tools {{ max-height: none; }}
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
      <div class="viewer-toolbar" aria-label="Drawing zoom controls">
        <button type="button" id="fitPageBtn">Fit Page</button>
        <button type="button" id="actualSizeBtn">100%</button>
        <button type="button" id="zoomOutBtn">Zoom Out</button>
        <button type="button" id="zoomInBtn">Zoom In</button>
        <span id="zoomLabel">Fit Page</span>
      </div>
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
        <h2>Measure Known Lengths</h2>
        <p class="hint">Click point A and point B on the drawing. Drag either endpoint afterward to fine-tune the measurement.</p>
        <div class="button-row">
          <button type="button" id="addMeasurementBtn">Add Measurement</button>
          <button type="button" class="danger" id="clearAllBtn">Clear All</button>
        </div>
        <label>Saved Measurements</label>
        <div class="measurement-list" id="measurementList"></div>
        <div class="measurement-summary" aria-label="Measurement totals">
          <div class="metric"><span>Complete Measurements</span><strong id="completeMeasurementCount">0</strong></div>
          <div class="metric"><span>Included in Takeoff</span><strong id="takeoffMeasurementCount">0</strong></div>
          <div class="metric"><span>Total PDF Units</span><strong id="totalPdfUnits">0</strong></div>
          <div class="metric"><span>Total Known Feet</span><strong id="totalKnownFeet">0</strong></div>
        </div>
        <label for="pointA">Point A</label>
        <input id="pointA" readonly />
        <label for="pointB">Point B</label>
        <input id="pointB" readonly />
        <label for="measuredPdfUnits">Measured PDF Units</label>
        <input id="measuredPdfUnits" />
        <label for="knownLengthFt">Known Real Length (feet)</label>
        <input id="knownLengthFt" placeholder="Example: 24" />
        <label class="check-row" for="takeoffToggle">
          <input id="takeoffToggle" type="checkbox" />
          Include this measurement in the takeoff
        </label>
        <label for="tradeSelect">Work Type</label>
        <select id="tradeSelect">
          <option value="manual_review">Review only / not priced</option>
          <option value="plumbing">Plumbing / pipe</option>
          <option value="mechanical">Mechanical / HVAC</option>
          <option value="electrical">Electrical / conduit</option>
          <option value="architectural">Architectural</option>
          <option value="structural">Structural</option>
          <option value="civil_site">Civil / site</option>
          <option value="concrete">Concrete</option>
          <option value="interiors_finishes">Finishes</option>
        </select>
        <label for="measurementTypeSelect">Takeoff Item</label>
        <select id="measurementTypeSelect">
          <option value="visual_length">Review measurement only</option>
          <option value="linear_item">Other linear item</option>
          <option value="pipe">Pipe</option>
          <option value="duct">Duct</option>
          <option value="conduit">Conduit</option>
          <option value="wall">Wall</option>
          <option value="curb">Curb</option>
          <option value="sawcut">Sawcut</option>
          <option value="trench">Trench</option>
          <option value="formwork">Formwork</option>
        </select>
        <label for="descriptionInput">Description</label>
        <input id="descriptionInput" placeholder="Example: 2 inch copper pipe above ceiling" />
        <label for="assemblyInput">Assembly or Cost Code</label>
        <input id="assemblyInput" placeholder="Example: 22 11 16 / P-001" />
        <div class="button-row">
          <button type="button" id="resetBtn">Reset Selected</button>
          <button type="button" class="danger" id="deleteMeasurementBtn">Delete Selected</button>
        </div>
        <button type="button" id="saveMeasurementsBtn">Save Measurements</button>
        <button type="button" class="primary" id="previewBtn">Preview Scale From Selected</button>
        <button type="button" class="apply" id="applyBtn">Apply Selected Scale to Job Result</button>
      </div>
      <div class="section">
        <h2>Result</h2>
        <div class="status" id="status">Ready. Click two points on the drawing.</div>
      </div>
    </aside>
  </main>
  <script>
    const svg = document.querySelector(".viewer svg");
    const viewer = document.getElementById("viewer");
    const fitPageBtn = document.getElementById("fitPageBtn");
    const actualSizeBtn = document.getElementById("actualSizeBtn");
    const zoomOutBtn = document.getElementById("zoomOutBtn");
    const zoomInBtn = document.getElementById("zoomInBtn");
    const zoomLabel = document.getElementById("zoomLabel");
    const statusBox = document.getElementById("status");
    const pointAInput = document.getElementById("pointA");
    const pointBInput = document.getElementById("pointB");
    const measuredInput = document.getElementById("measuredPdfUnits");
    const knownInput = document.getElementById("knownLengthFt");
    const takeoffToggle = document.getElementById("takeoffToggle");
    const tradeSelect = document.getElementById("tradeSelect");
    const measurementTypeSelect = document.getElementById("measurementTypeSelect");
    const descriptionInput = document.getElementById("descriptionInput");
    const assemblyInput = document.getElementById("assemblyInput");
    const tenantInput = document.getElementById("tenantId");
    const apiKeyInput = document.getElementById("apiKey");
    const measurementList = document.getElementById("measurementList");
    const completeMeasurementCount = document.getElementById("completeMeasurementCount");
    const takeoffMeasurementCount = document.getElementById("takeoffMeasurementCount");
    const totalPdfUnits = document.getElementById("totalPdfUnits");
    const totalKnownFeet = document.getElementById("totalKnownFeet");
    const sheetId = document.getElementById("sheetId").textContent.trim();
    const sourcePageIndex = Number(document.getElementById("pageIndex").textContent.trim()) || null;
    const jobId = document.getElementById("jobId").textContent.trim();
    const savedMeasurements = {saved_measurements_json};
    let measurements = [];
    let activeMeasurementId = null;
    let nextMeasurementNumber = 1;
    let overlayGroup = null;
    let draggingEndpoint = null;
    let suppressNextClick = false;
    let zoomPercent = 100;
    let saveReady = false;
    let saveTimer = null;
    svg.style.touchAction = "none";
    const tradeLabels = {{
      manual_review: "Review only",
      plumbing: "Plumbing",
      mechanical: "Mechanical / HVAC",
      electrical: "Electrical",
      architectural: "Architectural",
      structural: "Structural",
      civil_site: "Civil / site",
      concrete: "Concrete",
      interiors_finishes: "Finishes",
    }};
    const itemLabels = {{
      visual_length: "Review measurement",
      linear_item: "Linear item",
      pipe: "Pipe",
      duct: "Duct",
      conduit: "Conduit",
      wall: "Wall",
      curb: "Curb",
      sawcut: "Sawcut",
      trench: "Trench",
      formwork: "Formwork",
    }};
    const tradeItemValues = {{
      manual_review: ["visual_length"],
      plumbing: ["pipe", "trench", "linear_item"],
      mechanical: ["duct", "pipe", "linear_item"],
      electrical: ["conduit", "trench", "linear_item"],
      architectural: ["wall", "linear_item"],
      structural: ["wall", "formwork", "linear_item"],
      civil_site: ["curb", "sawcut", "trench", "linear_item"],
      concrete: ["formwork", "sawcut", "curb", "linear_item"],
      interiors_finishes: ["wall", "linear_item"],
    }};
    const defaultItemByTrade = {{
      manual_review: "visual_length",
      plumbing: "pipe",
      mechanical: "duct",
      electrical: "conduit",
      architectural: "wall",
      structural: "wall",
      civil_site: "curb",
      concrete: "formwork",
      interiors_finishes: "wall",
    }};

    function setStatus(value) {{
      statusBox.textContent = value;
    }}

    function svgNaturalWidth() {{
      const viewBox = svg.viewBox && svg.viewBox.baseVal;
      if (viewBox && Number.isFinite(viewBox.width) && viewBox.width > 0) return viewBox.width;
      const width = Number(svg.getAttribute("width"));
      return Number.isFinite(width) && width > 0 ? width : 1000;
    }}

    function updateZoomLabel(value) {{
      zoomLabel.textContent = value;
    }}

    function fitPage() {{
      zoomPercent = 100;
      svg.style.maxWidth = "100%";
      svg.style.width = "100%";
      svg.style.height = "auto";
      updateZoomLabel("Fit Page");
    }}

    function applyZoom(percent) {{
      zoomPercent = Math.max(25, Math.min(500, Number(percent) || 100));
      svg.style.maxWidth = "none";
      svg.style.width = `${{svgNaturalWidth() * zoomPercent / 100}}px`;
      svg.style.height = "auto";
      updateZoomLabel(`${{zoomPercent}}%`);
    }}

    function zoomBy(delta) {{
      applyZoom(zoomPercent + delta);
    }}

    function itemValuesForTrade(trade) {{
      const values = tradeItemValues[trade] || ["visual_length", "linear_item"];
      return Array.from(new Set(["visual_length", ...values]));
    }}

    function rebuildMeasurementTypeOptions(selectedValue = "visual_length", options = {{}}) {{
      const preserveUnknown = Boolean(options.preserveUnknown);
      const trade = tradeSelect.value || "manual_review";
      const values = itemValuesForTrade(trade);
      if (preserveUnknown && selectedValue && !values.includes(selectedValue)) {{
        values.push(selectedValue);
      }}
      measurementTypeSelect.replaceChildren();
      for (const value of values) {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = itemLabels[value] || value;
        measurementTypeSelect.appendChild(option);
      }}
      const fallback = defaultItemByTrade[trade] || "visual_length";
      measurementTypeSelect.value = values.includes(selectedValue) ? selectedValue : fallback;
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
      const matrix = svg.getScreenCTM();
      if (!matrix) return {{ x: 0, y: 0 }};
      const transformed = point.matrixTransform(matrix.inverse());
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

    function activeMeasurement() {{
      return measurements.find((m) => m.id === activeMeasurementId) || null;
    }}

    function measurementPdfUnits(measurement) {{
      const manual = Number(measurement.manualPdfUnits);
      if (Number.isFinite(manual) && manual > 0) return manual;
      if (measurement.a && measurement.b) return distance(measurement.a, measurement.b);
      return 0;
    }}

    function createMeasurement(initialPoint = null) {{
      const measurement = {{
        id: `measurement-${{Date.now()}}-${{nextMeasurementNumber}}`,
        label: `M${{nextMeasurementNumber}}`,
        a: initialPoint,
        b: null,
        manualPdfUnits: "",
        knownLengthFt: "",
        trade: "manual_review",
        measurementType: "visual_length",
        description: "",
        assembly: "",
        costCode: "",
        isTakeoffItem: false,
      }};
      nextMeasurementNumber += 1;
      measurements.push(measurement);
      activeMeasurementId = measurement.id;
      renderAll();
      return measurement;
    }}

    function hydrateSavedMeasurements() {{
      measurements = [];
      let maxNumber = 0;
      for (const raw of Array.isArray(savedMeasurements) ? savedMeasurements : []) {{
        const measurement = {{
          id: String(raw.id || `measurement-${{Date.now()}}-${{measurements.length + 1}}`),
          label: String(raw.label || `M${{measurements.length + 1}}`),
          a: pointFromStored(raw.a),
          b: pointFromStored(raw.b),
          manualPdfUnits: raw.measured_pdf_units ? String(raw.measured_pdf_units) : "",
          knownLengthFt: raw.known_length_ft ? String(raw.known_length_ft) : "",
          trade: String(raw.trade || "manual_review"),
          measurementType: String(raw.measurement_type || "visual_length"),
          description: String(raw.description || ""),
          assembly: String(raw.assembly || ""),
          costCode: String(raw.cost_code || ""),
          isTakeoffItem: Boolean(raw.is_takeoff_item),
        }};
        const numberMatch = measurement.label.match(/^M(\\d+)$/i);
        if (numberMatch) maxNumber = Math.max(maxNumber, Number(numberMatch[1]));
        measurements.push(measurement);
      }}
      nextMeasurementNumber = Math.max(maxNumber + 1, measurements.length + 1, 1);
      activeMeasurementId = measurements.length ? measurements[measurements.length - 1].id : null;
      if (!measurements.length) createMeasurement();
      renderAll();
      saveReady = true;
      setStatus(
        measurements.some((m) => m.a || m.b)
          ? `${{measurements.length}} saved measurement(s) loaded. Add, edit, drag, or save changes.`
          : "Ready. Click two points on the drawing."
      );
    }}

    function pointFromStored(value) {{
      if (!value || typeof value !== "object") return null;
      const x = Number(value.x);
      const y = Number(value.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      return {{ x, y }};
    }}

    function syncActiveFromInputs() {{
      const active = activeMeasurement();
      if (!active) return;
      active.knownLengthFt = knownInput.value.trim();
      const manual = measuredInput.value.trim();
      const geometric = active.a && active.b ? distance(active.a, active.b).toFixed(6) : "";
      active.manualPdfUnits = manual && manual !== geometric ? manual : "";
      active.isTakeoffItem = Boolean(takeoffToggle.checked);
      active.trade = tradeSelect.value || "manual_review";
      active.measurementType = measurementTypeSelect.value || "visual_length";
      active.description = descriptionInput.value.trim();
      active.assembly = assemblyInput.value.trim();
      active.costCode = assemblyInput.value.trim();
    }}

    function selectMeasurement(id) {{
      syncActiveFromInputs();
      activeMeasurementId = id;
      renderAll();
      const active = activeMeasurement();
      if (active) {{
        setStatus(`${{active.label}} selected. Click empty endpoints or drag the endpoint handles to adjust.`);
      }}
    }}

    function updateInputsFromActive() {{
      const active = activeMeasurement();
      pointAInput.value = active && active.a ? formatPoint(active.a) : "";
      pointBInput.value = active && active.b ? formatPoint(active.b) : "";
      if (active && active.manualPdfUnits) {{
        measuredInput.value = active.manualPdfUnits;
      }} else if (active && active.a && active.b) {{
        measuredInput.value = distance(active.a, active.b).toFixed(6);
      }} else {{
        measuredInput.value = "";
      }}
      knownInput.value = active ? active.knownLengthFt : "";
      takeoffToggle.checked = Boolean(active && active.isTakeoffItem);
      tradeSelect.value = active ? active.trade || "manual_review" : "manual_review";
      const activeItemType = active ? active.measurementType || "visual_length" : "visual_length";
      rebuildMeasurementTypeOptions(activeItemType, {{ preserveUnknown: true }});
      descriptionInput.value = active ? active.description || "" : "";
      assemblyInput.value = active ? active.assembly || active.costCode || "" : "";
    }}

    function renderMeasurementList() {{
      measurementList.replaceChildren();
      if (!measurements.length) {{
        const empty = document.createElement("p");
        empty.className = "hint";
        empty.textContent = "No measurements yet. Click the drawing or press Add Measurement.";
        measurementList.appendChild(empty);
        return;
      }}

      for (const measurement of measurements) {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "measurement-card" + (measurement.id === activeMeasurementId ? " active" : "");
        button.addEventListener("click", () => selectMeasurement(measurement.id));

        const title = document.createElement("div");
        title.className = "measurement-title";
        const name = document.createElement("strong");
        name.textContent = measurement.label;
        const state = document.createElement("span");
        state.textContent = measurement.a && measurement.b ? "Complete" : measurement.a ? "Needs B" : "Needs A";
        title.append(name, state);

        const meta = document.createElement("div");
        meta.className = "measurement-meta";
        const pdfUnits = measurementPdfUnits(measurement);
        const known = measurement.knownLengthFt ? ` | known ${{measurement.knownLengthFt}} ft` : "";
        const tradeLabel = tradeLabels[measurement.trade] || measurement.trade || "Review only";
        const itemLabel = itemLabels[measurement.measurementType] || measurement.measurementType || "Review measurement";
        const takeoffText = measurement.isTakeoffItem ? `${{tradeLabel}} / ${{itemLabel}}` : "Review only";
        const baseText = pdfUnits > 0 ? `${{pdfUnits.toFixed(4)}} PDF units${{known}}` : "Click two endpoints on the drawing.";
        meta.textContent = `${{baseText}} | ${{takeoffText}}`;

        button.append(title, meta);
        measurementList.appendChild(button);
      }}
    }}

    function formatTotal(value, digits = 4) {{
      if (!Number.isFinite(value) || value <= 0) return "0";
      return Number(value.toFixed(digits)).toLocaleString();
    }}

    function updateMeasurementTotals() {{
      let completeCount = 0;
      let takeoffCount = 0;
      let pdfTotal = 0;
      let knownTotal = 0;
      for (const measurement of measurements) {{
        if (measurement.a && measurement.b) completeCount += 1;
        if (measurement.isTakeoffItem) takeoffCount += 1;
        const measured = measurementPdfUnits(measurement);
        if (Number.isFinite(measured) && measured > 0) pdfTotal += measured;
        const known = Number(measurement.knownLengthFt);
        if (Number.isFinite(known) && known > 0) knownTotal += known;
      }}
      completeMeasurementCount.textContent = String(completeCount);
      takeoffMeasurementCount.textContent = String(takeoffCount);
      totalPdfUnits.textContent = formatTotal(pdfTotal);
      totalKnownFeet.textContent = `${{formatTotal(knownTotal, 2)}} ft`;
    }}

    function resetOverlay() {{
      if (overlayGroup) overlayGroup.remove();
      overlayGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
      overlayGroup.setAttribute("id", "measurement-overlay");
      svg.appendChild(overlayGroup);
    }}

    function drawPoint(measurement, endpoint, point) {{
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("class", "measure-point" + (measurement.id === activeMeasurementId ? "" : " inactive"));
      circle.setAttribute("cx", point.x);
      circle.setAttribute("cy", point.y);
      circle.setAttribute("r", measurement.id === activeMeasurementId ? "7" : "5.5");
      circle.dataset.measurementId = measurement.id;
      circle.dataset.endpoint = endpoint;
      circle.addEventListener("pointerdown", (event) => startEndpointDrag(event, measurement.id, endpoint));
      circle.addEventListener("click", (event) => event.stopPropagation());
      overlayGroup.appendChild(circle);
    }}

    function drawMeasurements() {{
      resetOverlay();
      for (const measurement of measurements) {{
        if (measurement.a && measurement.b) {{
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("class", "measure-line" + (measurement.id === activeMeasurementId ? " active" : ""));
          line.setAttribute("x1", measurement.a.x);
          line.setAttribute("y1", measurement.a.y);
          line.setAttribute("x2", measurement.b.x);
          line.setAttribute("y2", measurement.b.y);
          overlayGroup.appendChild(line);

          const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
          label.setAttribute("class", "measure-label");
          label.setAttribute("x", (measurement.a.x + measurement.b.x) / 2 + 8);
          label.setAttribute("y", (measurement.a.y + measurement.b.y) / 2 - 8);
          label.textContent = measurement.label;
          overlayGroup.appendChild(label);
        }}
        if (measurement.a) drawPoint(measurement, "a", measurement.a);
        if (measurement.b) drawPoint(measurement, "b", measurement.b);
      }}
    }}

    function renderAll() {{
      if (!activeMeasurementId && measurements.length) activeMeasurementId = measurements[0].id;
      renderMeasurementList();
      updateMeasurementTotals();
      drawMeasurements();
      updateInputsFromActive();
    }}

    function setActivePoint(endpoint, point) {{
      let active = activeMeasurement();
      if (!active) active = createMeasurement();
      active[endpoint] = point;
      active.manualPdfUnits = "";
      renderAll();
      scheduleSave();
      if (active.a && active.b) {{
        setStatus(`${{active.label}} measured ${{distance(active.a, active.b).toFixed(4)}} PDF units. Enter the real feet, then preview or apply scale.`);
      }} else {{
        setStatus(`${{active.label}} point A set. Click point B.`);
      }}
    }}

    function handleSheetClick(event) {{
      if (suppressNextClick || event.target.classList.contains("measure-point")) {{
        suppressNextClick = false;
        return;
      }}
      const point = svgPointFromEvent(event);
      let active = activeMeasurement();
      if (!active || (active.a && active.b)) {{
        active = createMeasurement(point);
        scheduleSave();
        setStatus(`${{active.label}} point A set. Click point B.`);
        return;
      }}
      if (!active.a) {{
        setActivePoint("a", point);
        return;
      }}
      setActivePoint("b", point);
    }}

    function startEndpointDrag(event, measurementId, endpoint) {{
      event.preventDefault();
      event.stopPropagation();
      selectMeasurement(measurementId);
      draggingEndpoint = {{ measurementId, endpoint, moved: false }};
      setStatus(`Dragging ${{endpoint.toUpperCase()}}. Release when the endpoint is on the exact drawing mark.`);
    }}

    function updateDraggedEndpoint(event) {{
      if (!draggingEndpoint) return;
      const active = measurements.find((m) => m.id === draggingEndpoint.measurementId);
      if (!active) return;
      active[draggingEndpoint.endpoint] = svgPointFromEvent(event);
      active.manualPdfUnits = "";
      draggingEndpoint.moved = true;
      renderAll();
    }}

    function endEndpointDrag() {{
      if (!draggingEndpoint) return;
      const active = measurements.find((m) => m.id === draggingEndpoint.measurementId);
      const moved = draggingEndpoint.moved;
      draggingEndpoint = null;
      if (moved) {{
        suppressNextClick = true;
        window.setTimeout(() => {{ suppressNextClick = false; }}, 0);
        scheduleSave();
      }}
      if (active && active.a && active.b) {{
        setStatus(`${{active.label}} adjusted to ${{distance(active.a, active.b).toFixed(4)}} PDF units.`);
      }}
    }}

    function resetSelected() {{
      const active = activeMeasurement();
      if (!active) return;
      active.a = null;
      active.b = null;
      active.manualPdfUnits = "";
      renderAll();
      scheduleSave();
      setStatus(`${{active.label}} reset. Click point A and point B again.`);
    }}

    function deleteSelected() {{
      const active = activeMeasurement();
      if (!active) return;
      measurements = measurements.filter((m) => m.id !== active.id);
      activeMeasurementId = measurements.length ? measurements[measurements.length - 1].id : null;
      if (!measurements.length) createMeasurement();
      renderAll();
      scheduleSave();
      setStatus("Selected measurement deleted.");
    }}

    function clearAllMeasurements() {{
      measurements = [];
      activeMeasurementId = null;
      nextMeasurementNumber = 1;
      createMeasurement();
      scheduleSave();
      setStatus("All measurements cleared. Click point A and point B on the drawing.");
    }}

    svg.addEventListener("click", handleSheetClick);
    window.addEventListener("pointermove", updateDraggedEndpoint);
    window.addEventListener("pointerup", endEndpointDrag);
    knownInput.addEventListener("input", () => {{
      const active = activeMeasurement();
      if (active) active.knownLengthFt = knownInput.value.trim();
      renderMeasurementList();
      scheduleSave();
    }});
    measuredInput.addEventListener("input", () => {{
      const active = activeMeasurement();
      if (active) active.manualPdfUnits = measuredInput.value.trim();
      renderMeasurementList();
      scheduleSave();
    }});
    function metadataInputChanged(options = {{}}) {{
      if (options.promoteTakeoffItem && takeoffToggle.checked && measurementTypeSelect.value === "visual_length") {{
        measurementTypeSelect.value = "linear_item";
      }}
      syncActiveFromInputs();
      renderMeasurementList();
      scheduleSave();
    }}
    takeoffToggle.addEventListener("change", () => metadataInputChanged({{ promoteTakeoffItem: true }}));
    tradeSelect.addEventListener("change", () => {{
      const currentItem = measurementTypeSelect.value || "visual_length";
      const defaultItem = defaultItemByTrade[tradeSelect.value] || currentItem;
      const nextItem = takeoffToggle.checked && currentItem === "visual_length" ? defaultItem : currentItem;
      rebuildMeasurementTypeOptions(nextItem);
      metadataInputChanged({{ promoteTakeoffItem: true }});
    }});
    measurementTypeSelect.addEventListener("change", metadataInputChanged);
    descriptionInput.addEventListener("input", metadataInputChanged);
    assemblyInput.addEventListener("input", metadataInputChanged);

    function measurementForStorage(measurement) {{
      const measured = measurementPdfUnits(measurement);
      const known = Number(measurement.knownLengthFt);
      const row = {{
        id: measurement.id,
        label: measurement.label,
        sheet_id: sheetId,
        source_page_index: sourcePageIndex,
        a: measurement.a,
        b: measurement.b,
        trade: measurement.trade || "manual_review",
        measurement_type: measurement.measurementType || "visual_length",
        description: measurement.description || "",
        assembly: measurement.assembly || "",
        cost_code: measurement.costCode || measurement.assembly || "",
        is_takeoff_item: Boolean(measurement.isTakeoffItem),
      }};
      if (Number.isFinite(measured) && measured > 0) row.measured_pdf_units = Number(measured.toFixed(6));
      if (Number.isFinite(known) && known > 0) row.known_length_ft = Number(known.toFixed(6));
      return row;
    }}

    function storableMeasurements() {{
      syncActiveFromInputs();
      return measurements
        .filter((m) => m.a || m.b || m.manualPdfUnits || m.knownLengthFt)
        .map(measurementForStorage);
    }}

    function scheduleSave() {{
      if (!saveReady) return;
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {{
        saveMeasurements({{ silent: true }}).catch((err) => {{
          setStatus(`Auto-save failed:\n${{err.message}}`);
        }});
      }}, 750);
    }}

    async function saveMeasurements(options = {{}}) {{
      const payload = {{
        sheet_id: sheetId,
        source_page_index: sourcePageIndex,
        measurements: storableMeasurements(),
      }};
      const response = await fetch(`/v1/jobs/${{encodeURIComponent(jobId)}}/visual-measurements`, {{
        method: "PUT",
        headers: {{
          ...headers(),
          "content-type": "application/json",
        }},
        body: JSON.stringify(payload),
      }});
      const text = await response.text();
      let body;
      try {{
        body = JSON.parse(text);
      }} catch (_err) {{
        throw new Error(text || "Server did not return JSON.");
      }}
      if (!response.ok) {{
        throw new Error(body.detail || text || `HTTP ${{response.status}}`);
      }}
      if (!options.silent) {{
        setStatus(`Saved ${{body.measurement_count}} measurement(s) for ${{sheetId}}.`);
      }}
      return body;
    }}

    function requireSelectedMeasurement() {{
      syncActiveFromInputs();
      const active = activeMeasurement();
      if (!active || !active.a || !active.b) {{
        throw new Error("Select a complete measurement first. Click two points or drag existing endpoints.");
      }}
      return active;
    }}

    async function callCalibration(method, endpoint) {{
      const active = requireSelectedMeasurement();
      const measured = Number(measuredInput.value);
      const known = Number(knownInput.value);
      if (!Number.isFinite(measured) || measured <= 0) {{
        throw new Error("Measured PDF Units must be greater than 0.");
      }}
      if (!Number.isFinite(known) || known <= 0) {{
        throw new Error("Known Real Length must be greater than 0.");
      }}
      active.manualPdfUnits = String(measured);
      active.knownLengthFt = String(known);
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

    document.getElementById("addMeasurementBtn").addEventListener("click", () => {{
      const measurement = createMeasurement();
      setStatus(`${{measurement.label}} added. Click point A and point B on the drawing.`);
    }});
    fitPageBtn.addEventListener("click", fitPage);
    actualSizeBtn.addEventListener("click", () => applyZoom(100));
    zoomOutBtn.addEventListener("click", () => zoomBy(-25));
    zoomInBtn.addEventListener("click", () => zoomBy(25));
    window.addEventListener("keydown", (event) => {{
      if (!event.ctrlKey && !event.metaKey) return;
      if (event.key === "+" || event.key === "=") {{
        event.preventDefault();
        zoomBy(25);
      }} else if (event.key === "-") {{
        event.preventDefault();
        zoomBy(-25);
      }} else if (event.key === "0") {{
        event.preventDefault();
        fitPage();
      }}
    }});
    document.getElementById("clearAllBtn").addEventListener("click", clearAllMeasurements);
    document.getElementById("resetBtn").addEventListener("click", resetSelected);
    document.getElementById("deleteMeasurementBtn").addEventListener("click", deleteSelected);
    document.getElementById("saveMeasurementsBtn").addEventListener("click", async () => {{
      try {{
        setStatus("Saving measurements...");
        await saveMeasurements();
      }} catch (err) {{
        setStatus(`Save failed:\n${{err.message}}`);
      }}
    }});
    document.getElementById("previewBtn").addEventListener("click", async () => {{
      try {{
        setStatus("Previewing scale...");
        const payload = await callCalibration("GET", `/v1/jobs/${{encodeURIComponent(jobId)}}/scale-calibration/preview`);
        const c = payload.calibration || {{}};
        const p = payload.preview || {{}};
        setStatus(
          `Preview complete.\n` +
          `Feet per PDF unit: ${{c.feet_per_pdf_unit}}\n` +
          `PDF units per foot: ${{c.pdf_units_per_foot}}\n` +
          `Calibrated vector linework: ${{p.calibrated_vector_linework_total_ft}} ft`
        );
      }} catch (err) {{
        setStatus(`Preview failed:\n${{err.message}}`);
      }}
    }});
    document.getElementById("applyBtn").addEventListener("click", async () => {{
      try {{
        setStatus("Applying scale to job result...");
        const payload = await callCalibration("POST", `/v1/jobs/${{encodeURIComponent(jobId)}}/scale-calibration/apply`);
        const c = payload.calibration || {{}};
        const p = payload.preview || {{}};
        setStatus(
          `Scale applied to job result.\n` +
          `Feet per PDF unit: ${{c.feet_per_pdf_unit}}\n` +
          `Updated linework: ${{p.calibrated_vector_linework_total_ft}} ft\n` +
          `Refresh the desktop job to see the updated takeoff.`
        );
      }} catch (err) {{
        setStatus(`Apply failed:\n${{err.message}}`);
      }}
    }});
    fitPage();
    hydrateSavedMeasurements();
    viewer.scrollTo({{ left: 0, top: 0, behavior: "instant" }});
  </script>
</body>
</html>"""


def list_visual_measurements(
    *,
    result: dict[str, Any] | None,
    sheet_id: str,
    source_page_index: int | None = None,
) -> list[dict[str, Any]]:
    """Return saved visual measurements for a sheet/page."""
    normalized_sheet_id = str(sheet_id or "").strip()
    if not normalized_sheet_id:
        return []
    annotations = _extract_annotations(result or {})
    rows = _dict_rows(annotations.get("manual_visual_measurements", []))
    selected: list[dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_visual_measurement(
            row,
            default_sheet_id=normalized_sheet_id,
            default_source_page_index=source_page_index,
        )
        if normalized is None:
            continue
        if str(normalized.get("sheet_id", "")).strip() != normalized_sheet_id:
            continue
        if (
            source_page_index is not None
            and _parse_positive_int(normalized.get("source_page_index")) != source_page_index
        ):
            continue
        selected.append(normalized)
    return selected[:MAX_VISUAL_MEASUREMENTS]


def save_visual_measurements_to_result(
    *,
    result: dict[str, Any] | None,
    sheet_id: str,
    source_page_index: int | None,
    measurements: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a result copy with visual sheet measurements persisted in annotations."""
    updated_result: dict[str, Any] = deepcopy(result or {})
    if not updated_result:
        raise ValueError("Completed job result is required before saving visual measurements.")
    normalized_sheet_id = str(sheet_id or "").strip()
    if not normalized_sheet_id:
        raise ValueError("sheet_id is required.")

    geometry = updated_result.get("geometry")
    if not isinstance(geometry, dict):
        geometry = {}
        updated_result["geometry"] = geometry
    annotations = geometry.get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}
        geometry["annotations"] = annotations

    existing = _dict_rows(annotations.get("manual_visual_measurements", []))
    retained = [
        row
        for row in existing
        if not _same_visual_measurement_scope(
            row,
            sheet_id=normalized_sheet_id,
            source_page_index=source_page_index,
        )
    ]
    normalized_rows: list[dict[str, Any]] = []
    for row in measurements[:MAX_VISUAL_MEASUREMENTS]:
        normalized = _normalize_visual_measurement(
            row,
            default_sheet_id=normalized_sheet_id,
            default_source_page_index=source_page_index,
        )
        if normalized is None:
            continue
        if not (normalized.get("a") or normalized.get("b")):
            continue
        normalized_rows.append(normalized)

    annotations["manual_visual_measurements"] = retained + normalized_rows
    quantity_takeoff, takeoff_issues = compute_quantity_takeoff(
        geometry,
        scale_analysis=updated_result.get("scale_analysis")
        if isinstance(updated_result.get("scale_analysis"), dict)
        else None,
    )
    updated_result["quantity_takeoff"] = quantity_takeoff
    _merge_result_issues(updated_result, takeoff_issues)

    payload = {
        "sheet_id": normalized_sheet_id,
        "source_page_index": source_page_index,
        "measurement_count": len(normalized_rows),
        "measurements": normalized_rows,
        "quantity_takeoff": quantity_takeoff,
        "note": "Visual measurements were saved to geometry.annotations.manual_visual_measurements.",
    }
    return updated_result, payload


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


def _script_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(max_chars - 3, 0)].rstrip() + "..."


def _normalize_visual_measurement(
    row: dict[str, Any],
    *,
    default_sheet_id: str,
    default_source_page_index: int | None,
) -> dict[str, Any] | None:
    sheet_id = str(row.get("sheet_id", default_sheet_id) or default_sheet_id).strip()
    if not sheet_id:
        return None
    source_page_index = _parse_positive_int(
        row.get("source_page_index", default_source_page_index)
    )
    measurement_id = _safe_short_text(row.get("id"), fallback=f"measurement-{len(str(row))}")
    label = _safe_short_text(row.get("label"), fallback="M")
    point_a = _point_dict(row.get("a"))
    point_b = _point_dict(row.get("b"))

    measured = _positive_float(
        row.get("measured_pdf_units", row.get("manualPdfUnits", row.get("measuredPdfUnits")))
    )
    if measured is None and point_a and point_b:
        measured = _distance_points(point_a, point_b)
    known = _positive_float(row.get("known_length_ft", row.get("knownLengthFt")))
    trade = _safe_short_text(row.get("trade"), fallback="manual_review", max_chars=60)
    measurement_type = _safe_short_text(
        row.get("measurement_type", row.get("measurementType")),
        fallback="visual_length",
        max_chars=60,
    )
    description = _safe_optional_text(row.get("description"), max_chars=180)
    assembly = _safe_optional_text(row.get("assembly"), max_chars=100)
    cost_code = _safe_optional_text(row.get("cost_code", row.get("costCode")), max_chars=100)
    is_takeoff_item = _to_bool(row.get("is_takeoff_item", row.get("isTakeoffItem")))

    normalized: dict[str, Any] = {
        "id": measurement_id,
        "label": label,
        "sheet_id": sheet_id,
        "source_page_index": source_page_index,
        "trade": trade,
        "measurement_type": measurement_type,
        "is_takeoff_item": is_takeoff_item,
    }
    if point_a is not None:
        normalized["a"] = point_a
    if point_b is not None:
        normalized["b"] = point_b
    if measured is not None:
        normalized["measured_pdf_units"] = round(measured, 6)
    if known is not None:
        normalized["known_length_ft"] = round(known, 6)
    if description:
        normalized["description"] = description
    if assembly:
        normalized["assembly"] = assembly
    if cost_code:
        normalized["cost_code"] = cost_code
    return normalized


def _same_visual_measurement_scope(
    row: dict[str, Any],
    *,
    sheet_id: str,
    source_page_index: int | None,
) -> bool:
    if str(row.get("sheet_id", "")).strip() != sheet_id:
        return False
    if source_page_index is None:
        return True
    return _parse_positive_int(row.get("source_page_index")) == source_page_index


def _point_dict(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    if value.get("x") in (None, "") or value.get("y") in (None, ""):
        return None
    x = _to_float(value.get("x"))
    y = _to_float(value.get("y"))
    return {"x": round(x, 6), "y": round(y, 6)}


def _distance_points(a: dict[str, float], b: dict[str, float]) -> float:
    dx = float(b["x"]) - float(a["x"])
    dy = float(b["y"]) - float(a["y"])
    return (dx * dx + dy * dy) ** 0.5


def _safe_short_text(value: Any, *, fallback: str, max_chars: int = 80) -> str:
    token = str(value or "").strip()
    if not token:
        token = fallback
    return token[:max_chars]


def _safe_optional_text(value: Any, *, max_chars: int = 120) -> str:
    token = str(value or "").strip()
    return token[:max_chars]


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _merge_result_issues(updated_result: dict[str, Any], new_issues: list[str]) -> None:
    issues = updated_result.get("issues_or_ambiguities", [])
    if not isinstance(issues, list):
        issues = []
    existing_strings = {str(item) for item in issues}
    merged = list(issues)
    for issue in new_issues:
        if issue not in existing_strings:
            merged.append(issue)
            existing_strings.add(issue)
    updated_result["issues_or_ambiguities"] = merged


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
