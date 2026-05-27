from __future__ import annotations

from service.trade_recommendation import build_trade_recommendation


def test_trade_recommendation_prefers_selected_for_stable_confidence():
    payload = build_trade_recommendation(
        job_id="job-1",
        result={
            "trade_scope": {
                "requested_mode": "auto",
                "requested_trades": [],
                "detected_trades": ["architectural", "electrical", "plumbing"],
                "sheet_trade_map": [
                    {"sheet": "A101", "trade": "architectural", "confidence": 0.91},
                    {"sheet": "E101", "trade": "electrical", "confidence": 0.82},
                    {"sheet": "P101", "trade": "plumbing", "confidence": 0.76},
                ],
            }
        },
    )

    assert payload["recommended_mode"] == "selected"
    assert payload["recommended_trades"] == ["architectural", "electrical", "plumbing"]
    assert payload["needs_user_review"] is False
    assert payload["confidence"] >= 0.6
    assert len(payload["trade_scores"]) == 3


def test_trade_recommendation_prefers_all_when_uncertain():
    payload = build_trade_recommendation(
        job_id="job-2",
        result={
            "trade_scope": {
                "requested_mode": "auto",
                "requested_trades": [],
                "detected_trades": ["architectural", "electrical", "plumbing", "mechanical_hvac"],
                "sheet_trade_map": [
                    {"sheet": "A101", "trade": "architectural", "confidence": 0.9},
                    {"sheet": "E101", "trade": "electrical", "confidence": 0.51},
                    {"sheet": "P101", "trade": "plumbing", "confidence": 0.45},
                    {"sheet": "M101", "trade": "mechanical_hvac", "confidence": 0.49},
                ],
            }
        },
    )

    assert payload["recommended_mode"] == "all"
    assert payload["recommended_trades"] == [
        "architectural",
        "electrical",
        "mechanical_hvac",
        "plumbing",
    ]
    assert payload["needs_user_review"] is True
    assert payload["confidence"] < 0.7


def test_trade_recommendation_handles_missing_result():
    payload = build_trade_recommendation(job_id="job-3", result=None)

    assert payload["recommended_mode"] == "all"
    assert payload["detected_trades"] == []
    assert payload["recommended_trades"] == []
    assert payload["confidence"] >= 0.05
