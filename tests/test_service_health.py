from service import app as service_app
from service.job_store import JobStore


def test_health_includes_build_and_process_metadata(monkeypatch, tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    monkeypatch.setattr(service_app, "_job_store", store)

    payload = service_app.health()

    assert payload["status"] == "ok"
    assert payload["app_version"]
    assert payload["started_at"]
    assert isinstance(payload["process_id"], int)
    assert payload["db_path"] == store.db_path
