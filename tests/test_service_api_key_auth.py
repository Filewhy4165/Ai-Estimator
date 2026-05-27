from service.app import _is_api_key_authorized


def test_is_api_key_authorized_accepts_exact_match():
    assert _is_api_key_authorized(expected="secret", provided="secret") is True


def test_is_api_key_authorized_rejects_missing_or_mismatch():
    assert _is_api_key_authorized(expected="secret", provided="") is False
    assert _is_api_key_authorized(expected="secret", provided="wrong") is False
    assert _is_api_key_authorized(expected="", provided="secret") is False
