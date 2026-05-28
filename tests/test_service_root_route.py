from service.app import root


def test_root_returns_html_landing_page():
    payload = root()

    assert "<title>AI Estimator Service</title>" in payload
    assert "API docs" in payload
    assert 'href="/docs"' in payload
    assert 'href="/health"' in payload
    assert 'href="/v1/jobs"' in payload
    assert 'href="/v1/meta/trades"' in payload
