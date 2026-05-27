from __future__ import annotations

import service.app as service_app


def test_resolve_auto_prune_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("AI_ESTIMATOR_PRUNE_ON_SUBMIT", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_PRUNE_LIMIT", raising=False)
    monkeypatch.delenv("AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS", raising=False)

    assert service_app._resolve_auto_prune_on_submit() is False
    assert service_app._resolve_auto_prune_older_than_hours() is None
    assert service_app._resolve_auto_prune_limit() == 200
    assert service_app._resolve_auto_prune_cleanup_uploads() is False

    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "true")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", "72")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_LIMIT", "99999")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS", "1")
    assert service_app._resolve_auto_prune_on_submit() is True
    assert service_app._resolve_auto_prune_older_than_hours() == 72
    assert service_app._resolve_auto_prune_limit() == 1000
    assert service_app._resolve_auto_prune_cleanup_uploads() is True

    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", "0")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_LIMIT", "invalid")
    assert service_app._resolve_auto_prune_older_than_hours() is None
    assert service_app._resolve_auto_prune_limit() == 200


def test_maybe_auto_prune_jobs_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "false")
    assert service_app._maybe_auto_prune_jobs() is None


def test_maybe_auto_prune_jobs_invokes_prune_when_enabled(monkeypatch):
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "true")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_OLDER_THAN_HOURS", "24")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_LIMIT", "50")
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_CLEANUP_UPLOADS", "true")

    calls: dict[str, object] = {}

    class _Payload:
        def model_dump(self) -> dict[str, object]:
            return {"ok": True}

    def _fake_prune_jobs(**kwargs):  # type: ignore[no-untyped-def]
        calls.update(kwargs)
        return _Payload()

    monkeypatch.setattr(service_app, "prune_jobs", _fake_prune_jobs)

    payload = service_app._maybe_auto_prune_jobs()
    assert payload == {"ok": True}
    assert calls == {
        "statuses": "completed,failed,canceled",
        "older_than_hours": 24,
        "limit": 50,
        "dry_run": False,
        "cleanup_uploads": True,
    }


def test_maybe_auto_prune_jobs_swallows_errors(monkeypatch):
    monkeypatch.setenv("AI_ESTIMATOR_PRUNE_ON_SUBMIT", "true")

    def _fake_prune_jobs(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(service_app, "prune_jobs", _fake_prune_jobs)
    assert service_app._maybe_auto_prune_jobs() is None
