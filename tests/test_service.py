import threading
import time

import pytest
from fastapi.testclient import TestClient

from test_api import app, auth


def test_late_result_cannot_overwrite_cancellation(app, monkeypatch):
    import hr_screening.engine
    original = hr_screening.engine.screen
    started, release = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(hr_screening.engine, 'screen', slow)
    with TestClient(app) as client:
        h = auth(client)
        task = client.post('/api/tasks', headers=h, json={'vacancy_id': 'v-python'}).json()
        thread = threading.Thread(target=app.state.service.run_task, args=(task['id'],))
        thread.start()
        assert started.wait(5)
        assert client.post(f"/api/tasks/{task['id']}/cancel", headers=h).status_code == 200
        release.set()
        thread.join(5)
        current = client.get(f"/api/tasks/{task['id']}", headers=h).json()
        assert current['status'] == 'destroyed'
        assert current['result'] is None


def test_tool_budget_and_timeout(app):
    user = app.state.store.get('user', 'recruiter')
    for limits in [{'max_tool_calls': 1}, {'max_seconds': 0}]:
        task = app.state.service.create(user, {'vacancy_id': 'v-python', 'limits': limits}, None)
        app.state.service.run_task(task['id'])
        got = app.state.store.get('task', task['id'])
        assert got['status'] == 'error'
        assert got['stage'] < 4
        assert 'quota' in got['error']


def test_backup_restores_task_and_audit(app, tmp_path):
    from hr_screening.store import Store
    user = app.state.store.get('user', 'recruiter')
    task = app.state.service.create(user, {'vacancy_id': 'v-python'}, None)
    target = tmp_path / 'backup.sqlite'
    app.state.store.backup(target)
    restored = Store(target)
    assert restored.get('task', task['id'])['status'] == 'created'
    assert restored.verify_audit()['valid']
    restored.close()


def test_large_resume_snapshot_is_separate_from_task_status(app):
    user = app.state.store.get('user', 'recruiter')
    task = app.state.service.create(user, {'vacancy_id': 'v-python'}, None)
    app.state.service.run_task(task['id'])
    current = app.state.store.get('task', task['id'])
    snapshot = app.state.store.get('snapshot', task['id'])
    assert snapshot and snapshot['resumes']
    assert 'resumes' not in current['checkpoint']
    assert current['checkpoint']['resume_snapshot'] == task['id']


def test_admin_cancellation_records_actual_role(app):
    with TestClient(app) as c:
        task = c.post('/api/tasks', headers=auth(c), json={'vacancy_id': 'v-python'}).json()
        admin = auth(c, 'admin', 'Admin-2026!')
        assert c.post(f"/api/tasks/{task['id']}/cancel", headers=admin).status_code == 200
        event = next(e for e in app.state.store.events() if e['action'] == 'task.cancel')
        assert event['actor'] == 'admin'
        assert event['role'] == 'admin'


def test_approval_rolls_back_when_audit_write_fails(app, monkeypatch):
    user = app.state.store.get('user', 'recruiter')
    task = app.state.service.create(user, {'vacancy_id': 'v-python'}, None)
    app.state.service.run_task(task['id'])
    task = app.state.store.get('task', task['id'])
    original = app.state.store.audit

    def fail(actor, role, tenant, project, action, detail):
        if action == 'task.approve':
            raise OSError('disk failure')
        return original(actor, role, tenant, project, action, detail)

    monkeypatch.setattr(app.state.store, 'audit', fail)
    with pytest.raises(OSError):
        app.state.service.control(user, task, 'approve', {'candidate_ids': [task['result']['candidates'][0]['candidate_id']]})
    assert app.state.store.get('task', task['id'])['status'] == 'waiting'


def test_error_cannot_overwrite_concurrent_cancel(app, monkeypatch):
    import hr_screening.engine
    store = app.state.store
    user = store.get('user', 'recruiter')
    task = app.state.service.create(user, {'vacancy_id': 'v-python'}, None)
    original = store.update
    tripped = [False]

    def failing(*args, **kwargs):
        raise RuntimeError('injected model failure')

    def update(kind, key, change):
        def race(t):
            candidate = change(dict(t))
            if candidate.get('status') == 'error' and not tripped[0]:
                tripped[0] = True
                t.update(status='destroyed', generation=t['generation'] + 1)
                return change(t)
            return candidate
        return original(kind, key, race)

    monkeypatch.setattr(hr_screening.engine, 'screen', failing)
    monkeypatch.setattr(store, 'update', update)
    app.state.service.run_task(task['id'])
    assert store.get('task', task['id'])['status'] == 'destroyed'


def test_pause_resume_does_not_reset_compute_budget(app, monkeypatch):
    import hr_screening.engine
    original = hr_screening.engine.screen
    started, release = threading.Event(), threading.Event()
    calls = [0]

    def slow(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            started.set()
            release.wait(3)
        time.sleep(.09)
        return original(*args, **kwargs)

    monkeypatch.setattr(hr_screening.engine, 'screen', slow)
    with TestClient(app) as c:
        h = auth(c)
        task = c.post('/api/tasks', headers=h, json={'vacancy_id': 'v-python', 'limits': {'max_seconds': .14}}).json()
        thread = threading.Thread(target=app.state.service.run_task, args=(task['id'],))
        thread.start()
        assert started.wait(3)
        time.sleep(.08)
        assert c.post(f"/api/tasks/{task['id']}/pause", headers=h).status_code == 200
        release.set()
        thread.join(3)
        assert c.post(f"/api/tasks/{task['id']}/resume", headers=h).status_code == 200
        app.state.service.run_task(task['id'])
        assert app.state.store.get('task', task['id'])['status'] == 'error'


def test_csv_neutralizes_formulas_and_client_export_uses_approved_subset(app):
    with TestClient(app) as c:
        h = auth(c)
        task = c.post('/api/tasks', headers=h, json={'vacancy_id': 'v-python'}).json()
        app.state.service.run_task(task['id'])
        app.state.store.update('task', task['id'], lambda t: {**t, 'result': {**t['result'], 'candidates': [{**x, 'name': '=SUM(1,1)'} for x in t['result']['candidates']]}})
        csv = c.get(f"/api/tasks/{task['id']}/export?format=csv", headers=h)
        assert "'=SUM(1,1)" in csv.text
