"""Изолированное сопоставление без загрузки моделей."""

import json
import os

import pytest


@pytest.fixture
def documents():
    vacancy = {"id": "v1", "title": "Python backend", "description": "Разработка API", "must_have": ["Python", "SQL"], "nice_to_have": [], "min_years": 2, "top_k": 2}
    resumes = [
        {"id": "weak", "name": "Первый кандидат", "text": "Работал с Excel.", "email": "weak@example.test"},
        {"id": "strong", "name": "Второй кандидат", "text": "Разрабатывал API на Python и SQL. Опыт работы: 4 года.", "email": "strong@example.test"},
    ]
    return vacancy, resumes


def test_execute_returns_evidence_and_process_metadata(documents):
    from hr_screening.compute import execute

    vacancy, resumes = documents
    result = execute(vacancy, resumes)
    first = result["candidates"][0]
    assert first["candidate_id"] == "strong"
    assert first["score"] == 100
    assert set(first["matched_skills"]) == {"python", "sql"}
    assert all(item["quote"] in resumes[1]["text"] for item in first["evidence"])
    assert result["compute"]["pid"] == os.getpid()
    json.dumps(result)


def test_pool_runs_in_separate_process_and_reuses_worker(documents):
    from hr_screening.compute import ComputePool

    vacancy, resumes = documents
    original = json.dumps(documents, ensure_ascii=False)
    pool = ComputePool(workers=1)
    try:
        first = pool.submit(vacancy, resumes).result(timeout=30)
        second = pool.submit(vacancy, resumes).result(timeout=30)
    finally:
        pool.close()
    assert first["compute"]["pid"] != os.getpid()
    assert first["compute"]["pid"] == second["compute"]["pid"]
    assert first["candidates"][0]["candidate_id"] == "strong"
    assert first["candidates"][0]["score"] > first["candidates"][1]["score"]
    assert second["candidates"] == first["candidates"]
    assert json.dumps(documents, ensure_ascii=False) == original


def test_closed_pool_rejects_new_jobs(documents):
    from hr_screening.compute import ComputePool

    pool = ComputePool()
    pool.close()
    with pytest.raises(RuntimeError):
        pool.submit(*documents)


def test_shared_event_cancels_work_before_execution(documents):
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    from hr_screening.compute import execute

    context = get_context("spawn")
    with context.Manager() as manager:
        event = manager.Event()
        event.set()
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
            future = executor.submit(execute, *documents, cancel_event=event)
            with pytest.raises(TimeoutError, match="cancelled"):
                future.result(timeout=30)


def test_future_exposes_shared_cancellation_event(documents):
    from hr_screening.compute import ComputePool

    pool = ComputePool()
    try:
        future = pool.submit(*documents)
        assert not future.cancel_event.is_set()
        future.cancel_event.set()
        assert future.cancel_event.is_set()
    finally:
        pool.close()
