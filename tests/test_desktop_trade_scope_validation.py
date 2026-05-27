from desktop.app import parse_selected_trade_tokens, validate_selected_trade_scope


def test_parse_selected_trade_tokens_dedupes_and_trims():
    tokens = parse_selected_trade_tokens(" architectural,plumbing, architectural , ,electrical ")
    assert tokens == ["architectural", "plumbing", "electrical"]


def test_validate_selected_trade_scope_requires_selected_tokens_for_selected_mode():
    try:
        validate_selected_trade_scope(
            analysis_mode="selected",
            selected_trades_csv="",
            valid_trades=["architectural", "plumbing"],
        )
    except ValueError as exc:
        assert "Selected mode" in str(exc)
    else:
        raise AssertionError("Expected selected mode without trades to raise ValueError")


def test_validate_selected_trade_scope_rejects_unknown_tokens_when_catalog_available():
    try:
        validate_selected_trade_scope(
            analysis_mode="selected",
            selected_trades_csv="architectural,not_a_trade",
            valid_trades=["architectural", "plumbing"],
        )
    except ValueError as exc:
        assert "Unknown trade" in str(exc)
    else:
        raise AssertionError("Expected unknown trades to raise ValueError")


def test_validate_selected_trade_scope_allows_unknown_tokens_without_catalog():
    tokens = validate_selected_trade_scope(
        analysis_mode="selected",
        selected_trades_csv="architectural,not_a_trade",
        valid_trades=None,
    )
    assert tokens == ["architectural", "not_a_trade"]
