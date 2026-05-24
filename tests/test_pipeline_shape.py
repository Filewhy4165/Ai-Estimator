from pathlib import Path

from ai_estimator.pipeline import run_pipeline
from ai_estimator.utils.json_validation import validate_output


def test_pipeline_output_matches_schema():
    payload = run_pipeline(
        pdf_paths=["C:/does/not/exist.pdf"],
        analysis_mode="auto",
        selected_trades=[],
        validate_schema=False,
    )

    schema_path = Path(__file__).resolve().parents[1] / "ai_estimator" / "schema" / "output_schema.json"
    valid, errors = validate_output(payload, str(schema_path))
    assert valid, errors

