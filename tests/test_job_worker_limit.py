from __future__ import annotations

import service.app as service_app


def test_resolve_job_worker_limit_defaults_and_invalid(monkeypatch):
    monkeypatch.delenv("AI_ESTIMATOR_JOB_WORKERS", raising=False)
    assert service_app._resolve_job_worker_limit() == 4

    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "invalid")
    assert service_app._resolve_job_worker_limit() == 4


def test_resolve_job_worker_limit_clamps_range(monkeypatch):
    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "0")
    assert service_app._resolve_job_worker_limit() == 1

    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "5")
    assert service_app._resolve_job_worker_limit() == 5

    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "999")
    assert service_app._resolve_job_worker_limit() == 32


def test_get_job_run_semaphore_rebuilds_when_limit_changes(monkeypatch):
    monkeypatch.setattr(service_app, "_job_run_semaphore", None)
    monkeypatch.setattr(service_app, "_job_run_semaphore_limit", None)

    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "2")
    sem_a = service_app._get_job_run_semaphore()
    limit_a = service_app._job_run_semaphore_limit
    assert limit_a == 2

    monkeypatch.setenv("AI_ESTIMATOR_JOB_WORKERS", "3")
    sem_b = service_app._get_job_run_semaphore()
    limit_b = service_app._job_run_semaphore_limit
    assert limit_b == 3
    assert sem_a is not sem_b
