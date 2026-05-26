from ai_estimator.extractors.pdf_loader import _choose_best_extracted_text, _text_quality_score


def test_choose_best_extracted_text_prefers_layout_when_richer():
    plain = "\n".join(
        [
            "NASA",
            "C D E F G",
            "A B",
        ]
    )
    layout = "\n".join(
        [
            "FAC-BT-4476-A1",
            "FLOOR PLAN, SCHEDULES AND NOTES",
            "SCALE: 1/8\" = 1'-0\"",
        ]
    )
    assert _choose_best_extracted_text(plain, layout) == layout


def test_choose_best_extracted_text_keeps_plain_when_layout_is_weaker():
    plain = "\n".join(
        [
            "A101 FIRST FLOOR PLAN",
            "SCALE: 1/8\" = 1'-0\"",
            "ARCHITECTURAL NOTES",
        ]
    )
    layout = "\n".join(
        [
            "NASA",
            "C D E F G",
            "A B",
        ]
    )
    assert _choose_best_extracted_text(plain, layout) == plain


def test_text_quality_score_rewards_sheet_id_signals():
    weak = "NASA\nC D E F G\nA B"
    strong = "FAC-AZ-4556-E1\nFLOOR PLANS, NOTES AND LEGEND\nSCALE: 1/8\" = 1'-0\""
    assert _text_quality_score(strong) > _text_quality_score(weak)

