from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_estimator.pipeline import (
    load_notes,
    load_sheet_overrides,
    run_pipeline,
    sanitize_selected_trades,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Estimator pipeline runner")
    parser.add_argument("--pdf", action="append", required=True, help="Path to PDF file. Repeat for multiple PDFs.")
    parser.add_argument(
        "--analysis-mode",
        choices=["auto", "selected", "all"],
        default="auto",
        help="Trade scope mode.",
    )
    parser.add_argument(
        "--selected-trades",
        default="",
        help="Comma-separated trades used when analysis-mode is selected.",
    )
    parser.add_argument("--sheet-overrides", default="", help="Optional sheet overrides JSON path.")
    parser.add_argument("--notes", default="", help="Optional notes file path.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument(
        "--schema-path",
        default="",
        help="Optional schema path. Defaults to package schema file.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Disable JSON schema validation.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    selected_trades = sanitize_selected_trades(args.selected_trades)
    sheet_overrides = load_sheet_overrides(args.sheet_overrides or None)
    notes = load_notes(args.notes or None)

    payload = run_pipeline(
        pdf_paths=args.pdf,
        analysis_mode=args.analysis_mode,
        selected_trades=selected_trades,
        sheet_overrides=sheet_overrides,
        notes=notes,
        validate_schema=not args.no_validate,
        schema_path=args.schema_path or None,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote estimator output to: {output_path}")
    print(f"Issues count: {len(payload.get('issues_or_ambiguities', []))}")


if __name__ == "__main__":
    main()

