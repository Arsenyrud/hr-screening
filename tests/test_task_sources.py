from fastapi.testclient import TestClient

from test_api import app, auth


def completed_snapshot(app, client, headers):
    task = client.post('/api/tasks', headers=headers, json={'vacancy_id': 'v-python'}).json()
    app.state.service.run_task(task['id'])
    return app.state.store.get('task', task['id'])


def test_task_source_returns_immutable_input_after_current_resume_changes(app):
    with TestClient(app) as client:
        headers = auth(client)
        original = app.state.store.get('resume', 'r01')
        task = completed_snapshot(app, client, headers)
        app.state.store.update('resume', 'r01', lambda record: {**record, 'text': 'Текущая версия резюме была заменена после выполнения задания.'})
        response = client.get(f"/api/tasks/{task['id']}/sources/r01", headers=headers)
        assert response.status_code == 200, response.text
        record = response.json()
        assert record['text'] == original['text']
        assert record['snapshot'] == {'task_id': task['id'], 'created_at': task['started_at']}
        event = next(event for event in app.state.store.events() if event['action'] == 'task.source.read')
        assert event['detail'] == {'task_id': task['id'], 'resume_id': 'r01'}
        assert original['text'] not in str(event)


def test_task_source_rejects_foreign_task_unknown_input_and_missing_snapshot(app):
    with TestClient(app) as client:
        headers = auth(client)
        task = completed_snapshot(app, client, headers)
        assert client.get(f"/api/tasks/{task['id']}/sources/r31", headers=headers).status_code == 404
        other = auth(client, 'recruiter-b', 'RecruiterB-2026!')
        assert client.get(f"/api/tasks/{task['id']}/sources/r01", headers=other).status_code == 404
        fresh = client.post('/api/tasks', headers=headers, json={'vacancy_id': 'v-python'}).json()
        assert client.get(f"/api/tasks/{fresh['id']}/sources/r01", headers=headers).status_code == 404


def test_task_source_is_available_only_to_recruiter(app):
    with TestClient(app) as client:
        task = completed_snapshot(app, client, auth(client))
        for username, password in [('client', 'Client-2026!'), ('admin', 'Admin-2026!'), ('auditor', 'Auditor-2026!')]:
            response = client.get(f"/api/tasks/{task['id']}/sources/r01", headers=auth(client, username, password))
            assert response.status_code == 403
