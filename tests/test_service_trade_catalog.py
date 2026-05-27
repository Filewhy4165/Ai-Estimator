from ai_estimator.constants import TRADE_NAMES
from service.app import get_trade_catalog


def test_trade_catalog_lists_modes_and_trades():
    payload = get_trade_catalog().model_dump()

    assert payload["analysis_modes"] == ["auto", "selected", "all"]
    assert len(payload["trades"]) == len(TRADE_NAMES)
    assert [row["trade"] for row in payload["trades"]] == TRADE_NAMES


def test_trade_catalog_includes_labels_and_csi_codes():
    payload = get_trade_catalog().model_dump()
    by_trade = {row["trade"]: row for row in payload["trades"]}

    assert by_trade["mechanical_hvac"]["label"] == "Mechanical HVAC"
    assert by_trade["electrical"]["csi_codes"] == ["26"]
    assert by_trade["general"]["csi_codes"] == []
