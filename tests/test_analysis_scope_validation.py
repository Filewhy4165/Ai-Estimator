from service.app import _validate_analysis_scope


def test_validate_analysis_scope_accepts_valid_inputs():
    _validate_analysis_scope(analysis_mode="auto", selected_trades=[])
    _validate_analysis_scope(analysis_mode="all", selected_trades=[])
    _validate_analysis_scope(analysis_mode="selected", selected_trades=["architectural"])


def test_validate_analysis_scope_rejects_invalid_mode():
    try:
        _validate_analysis_scope(analysis_mode="invalid", selected_trades=[])
    except ValueError as exc:
        assert "analysis_mode" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid analysis mode")


def test_validate_analysis_scope_rejects_selected_without_trades():
    try:
        _validate_analysis_scope(analysis_mode="selected", selected_trades=[])
    except ValueError as exc:
        assert "selected_trades" in str(exc)
    else:
        raise AssertionError("Expected ValueError for selected mode without valid trades")
