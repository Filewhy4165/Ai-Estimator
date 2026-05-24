from __future__ import annotations

import re

from ai_estimator.extractors.pdf_loader import LoadedPage
from ai_estimator.extractors.sheet_classifier import ClassifiedSheet


IMPERIAL_SCALE_RE = re.compile(r"SCALE\s*[:=]?\s*([0-9\/\"'\-\s=]+)", re.IGNORECASE)
METRIC_SCALE_RE = re.compile(r"SCALE\s*[:=]?\s*(1\s*:\s*\d+)", re.IGNORECASE)


def analyze_scales(
    pages: list[LoadedPage], sheets: list[ClassifiedSheet]
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    by_sheet: list[dict[str, object]] = []
    undetected: list[str] = []

    sheet_lookup = {sheet.source_page_index: sheet for sheet in sheets}
    for page in pages:
        sheet = sheet_lookup.get(page.page_index)
        sheet_id = sheet.sheet_id if sheet else f"PAGE_{page.page_index + 1}"

        metric = METRIC_SCALE_RE.search(page.text or "")
        imperial = IMPERIAL_SCALE_RE.search(page.text or "")
        detected = ""
        units = "unknown"
        confidence = 0.0
        if metric:
            detected = metric.group(1).strip()
            units = "metric"
            confidence = 0.85
        elif imperial:
            detected = imperial.group(1).strip()
            units = "imperial"
            confidence = 0.75
        else:
            undetected.append(sheet_id)

        by_sheet.append(
            {
                "sheet_id": sheet_id,
                "detected_scale": detected or None,
                "units": units,
                "confidence": round(confidence, 3),
            }
        )

    if undetected:
        issues.append(
            "Scale could not be determined for sheets: "
            + ", ".join(undetected[:20])
            + ". Provide a known dimension or explicit scale."
        )

    return {"by_sheet": by_sheet}, issues

