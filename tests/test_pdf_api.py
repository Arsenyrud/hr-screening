import base64
import hashlib

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from test_api import app, auth
from test_documents import make_pdf


def upload(client, headers, data=None, **fields):
    return client.post('/api/resumes/pdf', headers=headers, data={'name': 'Тестовый Кандидат', **fields}, files={'file': ('../../resume.pdf', make_pdf() if data is None else data, 'application/pdf')})


def test_pdf_import_download_and_backup_preserve_original_bytes(app, tmp_path):
    from hr_screening.store import Store
    original = make_pdf()
    with TestClient(app) as client:
        h = auth(client)
        response = upload(client, h, original)
        assert response.status_code == 201, response.text
        record = response.json()
        assert 'Python developer' in record['text']
        assert record['document'] == {'format': 'pdf', 'pages': 1, 'sha256': hashlib.sha256(original).hexdigest(), 'bytes': len(original), 'text_chars': len(record['text']), 'filename': 'resume.pdf'}
        assert record['tenant_id'] == 'agency-a' and record['project_id'] == 'alpha'
        assert 'data_b64' not in record
        downloaded = client.get(f"/api/resumes/{record['id']}/pdf", headers=h)
        assert downloaded.status_code == 200
        assert downloaded.content == original
        assert downloaded.headers['content-type'] == 'application/pdf'
        assert downloaded.headers['content-disposition'] == f'attachment; filename="resume-{record["id"]}.pdf"'
        target = tmp_path / 'pdf-backup.sqlite'
        app.state.store.backup(target)
        restored = Store(target)
        assert base64.b64decode(restored.get('attachment', record['id'])['data_b64']) == original
        restored.close()
        events = app.state.store.events()
        assert {'resume.pdf.import', 'resume.pdf.read'} <= {e['action'] for e in events}
        assert all('Python developer' not in str(e['detail']) for e in events)


def test_pdf_import_and_read_enforce_role_tenant_project_acl(app):
    with TestClient(app) as client:
        assert upload(client, {}).status_code == 401
        recruiter = auth(client)
        assert upload(client, recruiter, project_id='beta').status_code == 403
        record = upload(client, recruiter).json()
        for username, password in [('client', 'Client-2026!'), ('admin', 'Admin-2026!'), ('auditor', 'Auditor-2026!')]:
            h = auth(client, username, password)
            assert upload(client, h).status_code == 403
            assert client.get(f"/api/resumes/{record['id']}/pdf", headers=h).status_code == 403
        other = auth(client, 'recruiter-b', 'RecruiterB-2026!')
        assert client.get(f"/api/resumes/{record['id']}/pdf", headers=other).status_code == 404
        assert client.get('/api/resumes/r01/pdf', headers=recruiter).status_code == 404


@pytest.mark.parametrize('data', [b'not a PDF', b'%PDF-1.7\nbroken', make_pdf(text=''), make_pdf(text='', image=True), make_pdf(encrypted=True), make_pdf(pages=21)])
def test_invalid_pdf_does_not_create_resume_or_attachment(app, data):
    with TestClient(app) as client:
        h = auth(client)
        before = len(app.state.store.list('resume'))
        response = upload(client, h, data)
        assert response.status_code == 422, response.text
        assert len(app.state.store.list('resume')) == before
        assert app.state.store.list('attachment') == []


def test_pdf_fields_and_names_are_validated(app):
    with TestClient(app) as client:
        h = auth(client)
        assert upload(client, h, name='X').status_code == 422
        assert upload(client, h, tenant_id='agency-b').status_code == 422
        duplicate = client.post('/api/resumes/pdf', headers=h, files=[('file', ('resume.pdf', make_pdf(), 'application/pdf')), ('name', (None, 'First Name')), ('name', (None, 'Other Name'))])
        assert duplicate.status_code == 422
        extra_file = client.post('/api/resumes/pdf', headers=h, data={'name': 'Test Candidate'}, files=[('file', ('resume.pdf', make_pdf(), 'application/pdf')), ('another', ('extra.pdf', make_pdf(), 'application/pdf'))])
        assert extra_file.status_code == 422


def test_broken_multipart_is_a_validation_error(app):
    with TestClient(app) as client:
        h = auth(client)
        response = client.post('/api/resumes/pdf', headers={**h, 'Content-Type': 'multipart/form-data; boundary=test'}, content=b'not-a-multipart-body')
        assert response.status_code == 422


def test_busy_pdf_parser_returns_retryable_error_without_import(app):
    from hr_screening import documents
    with TestClient(app) as client:
        h = auth(client)
        documents.PARSER_SLOTS.acquire()
        documents.PARSER_SLOTS.acquire()
        try:
            response = upload(client, h)
        finally:
            documents.PARSER_SLOTS.release()
            documents.PARSER_SLOTS.release()
        assert response.status_code == 429
        assert response.headers['retry-after'] == '1'
        assert app.state.store.list('attachment') == []


def test_pdf_file_and_request_body_limits_apply_before_multipart_parse(app, monkeypatch):
    with TestClient(app) as client:
        h = auth(client)
        assert upload(client, h, make_pdf() + b' ' * (5 * 1024 * 1024)).status_code == 413
        def forbidden(*args, **kwargs):
            raise AssertionError('Multipart parser must not see an oversized request')
        monkeypatch.setattr(Request, 'form', forbidden)
        oversized = client.post('/api/resumes/pdf', headers={**h, 'Content-Type': 'multipart/form-data; boundary=test'}, content=(b'x' * (1024 * 1024) for _ in range(7)))
        assert oversized.status_code == 413


def test_pdf_import_rolls_back_when_audit_fails(app, monkeypatch):
    with TestClient(app, raise_server_exceptions=False) as client:
        h = auth(client)
        before = len(app.state.store.list('resume'))
        original = app.state.store.audit
        def fail(actor, role, tenant, project, action, detail):
            if action == 'resume.pdf.import':
                raise OSError('audit unavailable')
            return original(actor, role, tenant, project, action, detail)
        monkeypatch.setattr(app.state.store, 'audit', fail)
        assert upload(client, h).status_code == 500
        assert len(app.state.store.list('resume')) == before
        assert app.state.store.list('attachment') == []
