import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    from hr_screening.api import create_app
    from hr_screening.seed import seed
    app = create_app(str(tmp_path / 'test.db'), start_worker=False)
    seed(app.state.store)
    return app


def auth(client, username='recruiter', password='Recruiter-2026!'):
    response = client.post('/api/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def test_auth_and_project_isolation(app):
    with TestClient(app) as c:
        assert c.get('/api/resumes').status_code == 401
        h = auth(c)
        resumes = c.get('/api/resumes', headers=h).json()
        assert resumes
        assert all(r['tenant_id'] == 'agency-a' and r['project_id'] == 'alpha' for r in resumes)
        foreign = next(v for v in app.state.store.list('vacancy') if v['tenant_id'] != 'agency-a')
        assert c.post('/api/tasks', headers=h, json={'vacancy_id': foreign['id']}).status_code == 404
        assert c.post('/api/resumes', headers=h, json={'name': 'Other', 'text': 'Python developer', 'project_id': 'beta'}).status_code == 403
        events = c.get('/api/audit', headers=h).json()
        assert any(e['action'] == 'access.denied' for e in events)
        assert app.state.store.verify_audit()['valid']


def test_client_cannot_read_drafts_or_resume_bank(app):
    with TestClient(app) as c:
        h = auth(c, 'client', 'Client-2026!')
        assert c.get('/api/resumes', headers=h).status_code == 403
        assert c.get('/api/tasks', headers=h).json() == []
        assert c.post('/api/tasks', headers=h, json={'vacancy_id': 'v-python'}).status_code == 403


def test_second_tenant_recruiter_can_use_own_vacancy(app):
    with TestClient(app) as c:
        h = auth(c, 'recruiter-b', 'RecruiterB-2026!')
        vacancies = c.get('/api/vacancies', headers=h).json()
        assert 'v-frontend' in {v['id'] for v in vacancies}
        assert all(v['tenant_id'] == 'agency-b' for v in vacancies)
        resumes = c.get('/api/resumes', headers=h).json()
        assert resumes and all(r['tenant_id'] == 'agency-b' for r in resumes)


def test_task_lifecycle_idempotency_and_approval(app):
    with TestClient(app) as c:
        h = auth(c)
        vacancy = c.get('/api/vacancies', headers=h).json()[0]
        headers = {**h, 'Idempotency-Key': 'test-key'}
        a = c.post('/api/tasks', headers=headers, json={'vacancy_id': vacancy['id']})
        assert a.status_code == 201, a.text
        task = a.json()
        b = c.post('/api/tasks', headers=headers, json={'vacancy_id': vacancy['id']})
        assert b.json()['id'] == task['id']
        tid = task['id']
        assert c.post(f'/api/tasks/{tid}/approve', headers=h, json={'candidate_ids': ['x']}).status_code == 409
        assert c.post(f'/api/tasks/{tid}/pause', headers=h).json()['status'] == 'paused'
        assert c.post(f'/api/tasks/{tid}/resume', headers=h).json()['status'] == 'created'
        app.state.service.run_task(tid)
        task = c.get(f'/api/tasks/{tid}', headers=h).json()
        assert task['status'] == 'waiting', task
        assert task['result']['candidates']
        assert c.post(f'/api/tasks/{tid}/approve', headers=h, json={'candidate_ids': ['foreign']}).status_code == 422
        selected = [task['result']['candidates'][0]['candidate_id']]
        approved = c.post(f'/api/tasks/{tid}/approve', headers=h, json={'candidate_ids': selected, 'comment': 'Проверено по резюме'})
        assert approved.status_code == 200, approved.text
        assert approved.json()['status'] == 'completed'
        assert c.post(f'/api/tasks/{tid}/resume', headers=h).status_code == 409
        ch = auth(c, 'client', 'Client-2026!')
        view = c.get(f'/api/tasks/{tid}', headers=ch).json()
        assert [r['candidate_id'] for r in view['result']['candidates']] == selected
        assert 'email' not in str(view['result']['candidates'])
        exported = c.get(f'/api/tasks/{tid}/export?format=csv', headers=ch)
        assert exported.status_code == 200
        assert 'candidate_id' in exported.text


def test_cancellation_and_candidate_quota(app):
    with TestClient(app) as c:
        h = auth(c)
        vacancy = c.get('/api/vacancies', headers=h).json()[0]
        t = c.post('/api/tasks', headers=h, json={'vacancy_id': vacancy['id']}).json()
        assert c.post(f"/api/tasks/{t['id']}/cancel", headers=h).json()['status'] == 'destroyed'
        app.state.service.run_task(t['id'])
        assert c.get(f"/api/tasks/{t['id']}", headers=h).json()['status'] == 'destroyed'
        q = c.post('/api/tasks', headers=h, json={'vacancy_id': vacancy['id'], 'limits': {'max_candidates': 1}}).json()
        app.state.service.run_task(q['id'])
        got = c.get(f"/api/tasks/{q['id']}", headers=h).json()
        assert got['status'] == 'error'
        assert 'quota' in got['error']


def test_admin_and_auditor_have_no_resume_access(app):
    with TestClient(app) as c:
        for user, pwd in [('admin', 'Admin-2026!'), ('auditor', 'Auditor-2026!')]:
            h = auth(c, user, pwd)
            assert c.get('/api/resumes', headers=h).status_code == 403
            assert c.get('/api/audit', headers=h).status_code == 200
        assert c.get('/api/admin', headers=auth(c, 'admin', 'Admin-2026!')).status_code == 200
        assert c.get('/api/admin', headers=auth(c)).status_code == 403


def test_recovery_preserves_checkpoint(app):
    from hr_screening.service import ScreeningService
    user = app.state.store.get('user', 'recruiter')
    task = app.state.service.create(user, {'vacancy_id': 'v-python'}, None)
    app.state.store.update('task', task['id'], lambda t: {**t, 'status': 'running', 'stage': 1, 'checkpoint': {'test': 'durable'}})
    other = ScreeningService(app.state.store)
    other.recover()
    got = app.state.store.get('task', task['id'])
    assert got['status'] == 'created'
    assert got['checkpoint'] == {'test': 'durable'}
    assert got['stage'] == 1
    assert any(e['action'] == 'task.recovered' for e in app.state.store.events())


def test_audit_detects_tampering(app):
    app.state.store.audit('recruiter', 'recruiter', 'agency-a', 'alpha', 'test', {})
    assert app.state.store.verify_audit()['valid']
    with app.state.store.transaction() as con:
        con.execute("UPDATE audit SET action='tampered' WHERE seq=1")
    assert not app.state.store.verify_audit()['valid']
