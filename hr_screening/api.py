"""HTTP API и интерфейс."""

import base64
import csv
import io
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from .security import password_ok, public_user, require, scope, token_hash
from .documents import MAX_BODY_BYTES, MAX_PDF_BYTES, PDFBusyError, parse_pdf
from .service import ScreeningService
from .store import Store, now, packed


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class Vacancy(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=20000)
    must_have: list[str] = Field(default_factory=list, max_length=30)
    nice_to_have: list[str] = Field(default_factory=list, max_length=30)
    min_years: float = Field(default=0, ge=0, le=60)
    top_k: int = Field(default=5, ge=1, le=30)
    project_id: str = 'alpha'
    tenant_id: str | None = None


class Resume(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    text: str = Field(min_length=10, max_length=30000)
    email: str = Field(default='', max_length=200)
    project_id: str = 'alpha'
    tenant_id: str | None = None


class Limits(StrictModel):
    max_seconds: float = Field(default=180, ge=.01, le=600)
    max_candidates: int = Field(default=500, ge=1, le=2000)
    max_tool_calls: int = Field(default=12, ge=1, le=30)


class TaskRequest(StrictModel):
    vacancy_id: str = Field(min_length=1, max_length=100)
    limits: Limits | None = None


class Approval(StrictModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=30)
    comment: str = Field(default='', max_length=2000)


def create_app(db_path=None, start_worker=True):
    store = Store(db_path or os.environ.get('HR_DB', 'runtime/hr.sqlite'))
    service = ScreeningService(store, os.environ.get('HR_MODEL_PATH'), int(os.environ.get('HR_WORKERS', '4')), os.environ.get('HR_LLM_PATH'))
    durations, errors, requests = deque(maxlen=10000), [0], [0]
    attempts = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            service.start()
        yield
        service.shutdown()
        store.close()

    app = FastAPI(title='HR Скрининг', version='1.0.0', lifespan=lifespan)
    app.state.store, app.state.service = store, service

    @app.middleware('http')
    async def observe(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        durations.append((time.perf_counter() - started) * 1000)
        requests[0] += 1
        errors[0] += response.status_code >= 500
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
        return response

    def user(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(401, 'Войдите в систему')
        session = store.get('session', token_hash(authorization[7:]))
        if not session or session['expires_at'] < time.time():
            raise HTTPException(401, 'Сессия истекла')
        account = store.get('user', session['user_id'])
        if not account:
            raise HTTPException(401, 'Пользователь не найден')
        return account

    def visible_task(account, task_id):
        task = store.get('task', task_id)
        if not task or not scope(account, task) or (account['role'] == 'client' and task['status'] != 'completed'):
            store.audit(account['id'], account['role'], account['tenant_id'], None, 'access.denied', {'operation': 'task.read', 'task_id': task_id})
            raise HTTPException(404, 'Задание не найдено')
        require(store, account, {'recruiter', 'admin', 'client'}, task)
        return task

    def task_view(account, task):
        result = {k: v for k, v in task.items() if k not in {'checkpoint', 'idempotency_key', 'vacancy', 'requested_limits'}}
        if account['role'] == 'admin':
            result['result'] = None
            result.pop('approval_comment', None)
        if account['role'] == 'client' and result['result']:
            result['result'] = {**result['result'], 'candidates': [c for c in result['result']['candidates'] if c['candidate_id'] in task['approved_ids']]}
            result['result'].pop('duplicates', None)
            result['result'].pop('provenance', None)
        return result

    @app.get('/health')
    def health():
        store.get('health', 'probe')
        return {'status': 'ok', 'version': '1.0.0'}

    @app.post('/api/login')
    def login(body: Login, request: Request):
        addr = request.client.host if request.client else 'local'
        stamps = attempts[addr]
        while stamps and stamps[0] < time.time() - 60:
            stamps.popleft()
        if len(stamps) >= 20:
            raise HTTPException(429, 'Слишком много попыток входа')
        account = store.get('user', body.username)
        if not account or not password_ok(body.password, account['password_hash']):
            stamps.append(time.time())
            store.audit(body.username, 'anonymous', None, None, 'login.denied', {})
            raise HTTPException(401, 'Неверный логин или пароль')
        token = secrets.token_urlsafe(32)
        store.put('session', {'id': token_hash(token), 'user_id': account['id'], 'expires_at': time.time() + 8 * 3600})
        store.audit(account['id'], account['role'], account['tenant_id'], None, 'login.success', {})
        return {'token': token, 'user': public_user(account)}

    @app.get('/api/me')
    def me(account=Depends(user)):
        return public_user(account)

    @app.get('/api/vacancies')
    def vacancies(account=Depends(user)):
        require(store, account, {'recruiter', 'client'})
        return [v for v in store.list('vacancy') if scope(account, v)]

    @app.post('/api/vacancies', status_code=201)
    def vacancy_create(body: Vacancy, account=Depends(user)):
        return create_document('vacancy', body, account)

    @app.get('/api/resumes')
    def resumes(account=Depends(user)):
        require(store, account, {'recruiter'})
        values = [v for v in store.list('resume') if scope(account, v)]
        store.audit(account['id'], account['role'], account['tenant_id'], None, 'resumes.read', {'count': len(values)})
        return values

    @app.post('/api/resumes', status_code=201)
    def resume_create(body: Resume, account=Depends(user)):
        return create_document('resume', body, account)

    @app.post('/api/resumes/pdf', status_code=201)
    async def resume_pdf(request: Request, account=Depends(user)):
        require(store, account, {'recruiter'})
        if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
            raise HTTPException(422, 'Передайте PDF и поля формы multipart/form-data')
        try:
            content_length = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(422, 'Некорректный Content-Length')
        if content_length > MAX_BODY_BYTES:
            raise HTTPException(413, 'Запрос превышает 6 MiB')
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, 'Запрос превышает 6 MiB')
            payload.extend(chunk)
        async def replay():
            return {'type': 'http.request', 'body': bytes(payload), 'more_body': False}
        bounded = Request(request.scope, replay)
        try:
            async with bounded.form(max_files=1, max_fields=3, max_part_size=2048) as form:
                keys = [key for key, _ in form.multi_items()]
                if set(keys) - {'file', 'name', 'email', 'project_id'} or len(keys) != len(set(keys)):
                    raise HTTPException(422, 'Лишние или повторяющиеся поля PDF-формы')
                file = form.get('file')
                if not isinstance(file, UploadFile) or not isinstance(form.get('name'), str) or any(isinstance(form.get(key), UploadFile) for key in ('name', 'email', 'project_id')):
                    raise HTTPException(422, 'Нужны один файл PDF и имя кандидата')
                try:
                    metadata = Resume(name=form['name'], email=form.get('email', ''), project_id=form.get('project_id', 'alpha'), text='PDF text placeholder')
                except ValidationError:
                    raise HTTPException(422, 'Проверьте имя, email и проект кандидата')
                require(store, account, {'recruiter'}, {'tenant_id': account['tenant_id'], 'project_id': metadata.project_id})
                raw = await file.read(MAX_PDF_BYTES + 1)
                if len(raw) > MAX_PDF_BYTES:
                    raise HTTPException(413, 'PDF превышает 5 MiB')
                filename = (file.filename or 'resume.pdf').replace('\\', '/').rsplit('/', 1)[-1]
                filename = ''.join(ch for ch in filename if ch.isprintable()).strip(' .')[:200] or 'resume.pdf'
        except MultipartParseError as exc:
            raise HTTPException(422, 'Некорректная multipart-форма PDF') from exc
        except StarletteHTTPException as exc:
            if exc.status_code == 400:
                raise HTTPException(422, 'Некорректная multipart-форма PDF') from exc
            raise
        try:
            parsed = await run_in_threadpool(parse_pdf, raw)
        except PDFBusyError as exc:
            raise HTTPException(429, str(exc), headers={'Retry-After': '1'}) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        item = {**metadata.model_dump(), 'id': uuid.uuid4().hex, 'tenant_id': account['tenant_id'], 'text': parsed['text'], 'updated_at': now(),
                'document': {'format': 'pdf', **{k: v for k, v in parsed.items() if k != 'text'}, 'filename': filename}}
        with store.transaction():
            store.put('resume', item)
            store.put('attachment', {'id': item['id'], 'tenant_id': item['tenant_id'], 'project_id': item['project_id'], 'format': 'pdf', 'data_b64': base64.b64encode(raw).decode('ascii')})
            store.audit(account['id'], account['role'], account['tenant_id'], item['project_id'], 'resume.pdf.import', {'id': item['id'], **{k: parsed[k] for k in ('pages', 'sha256', 'bytes')}})
        return item

    @app.get('/api/resumes/{resume_id}/pdf')
    def resume_pdf_download(resume_id: str, account=Depends(user)):
        require(store, account, {'recruiter'})
        record = store.get('resume', resume_id)
        if not record or not scope(account, record):
            store.audit(account['id'], account['role'], account['tenant_id'], None, 'access.denied', {'operation': 'resume.pdf.read', 'resume_id': resume_id})
            raise HTTPException(404, 'PDF резюме не найден')
        attachment = store.get('attachment', resume_id)
        if not attachment or attachment.get('format') != 'pdf' or not scope(account, attachment):
            raise HTTPException(404, 'PDF резюме не найден')
        raw = base64.b64decode(attachment['data_b64'], validate=True)
        store.audit(account['id'], account['role'], account['tenant_id'], record['project_id'], 'resume.pdf.read', {'id': resume_id})
        return Response(raw, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="resume-{resume_id}.pdf"'})

    def create_document(kind, body, account):
        item = {**body.model_dump(), 'id': uuid.uuid4().hex, 'tenant_id': body.tenant_id or account['tenant_id'], 'updated_at': now()}
        require(store, account, {'recruiter'}, item)
        store.put(kind, item)
        store.audit(account['id'], account['role'], account['tenant_id'], item['project_id'], kind + '.created', {'id': item['id']})
        return item

    @app.post('/api/tasks', status_code=201)
    def task_create(body: TaskRequest, idempotency_key: str | None = Header(default=None), account=Depends(user)):
        if idempotency_key and len(idempotency_key) > 128:
            raise HTTPException(422, 'Слишком длинный Idempotency-Key')
        data = body.model_dump(exclude_none=True)
        return task_view(account, service.create(account, data, idempotency_key))

    @app.get('/api/tasks')
    def tasks(account=Depends(user)):
        require(store, account, {'recruiter', 'admin', 'client'})
        ordered = sorted(store.list('task'), key=lambda task: task['created_at'], reverse=True)
        return [task_view(account, t) for t in ordered if scope(account, t) and (account['role'] != 'client' or t['status'] == 'completed')]

    @app.get('/api/tasks/{task_id}')
    def task_read(task_id: str, account=Depends(user)):
        return task_view(account, visible_task(account, task_id))

    @app.get('/api/tasks/{task_id}/sources/{resume_id}')
    def task_source(task_id: str, resume_id: str, account=Depends(user)):
        require(store, account, {'recruiter'})
        task = visible_task(account, task_id)
        snapshot = store.get('snapshot', task_id)
        record = next((record for record in (snapshot or {}).get('resumes', []) if record['id'] == resume_id), None)
        if not record or not scope(account, record):
            raise HTTPException(404, 'Источник отсутствует в снимке задания')
        store.audit(account['id'], account['role'], account['tenant_id'], task['project_id'], 'task.source.read', {'task_id': task_id, 'resume_id': resume_id})
        return {**record, 'snapshot': {'task_id': task_id, 'created_at': task.get('started_at') or task['created_at']}}

    @app.post('/api/tasks/{task_id}/{action}')
    def task_action(task_id: str, action: Literal['pause', 'resume', 'cancel', 'approve'], body: Approval | None = None, account=Depends(user)):
        result = service.control(account, visible_task(account, task_id), action, body.model_dump() if body else None)
        return task_view(account, result)

    @app.get('/api/tasks/{task_id}/export')
    def export(task_id: str, format: Literal['json', 'csv', 'md'] = 'json', account=Depends(user)):
        require(store, account, {'recruiter', 'client'})
        task = task_view(account, visible_task(account, task_id))
        if not task['result']:
            raise HTTPException(409, 'Результат еще не готов')
        store.audit(account['id'], account['role'], account['tenant_id'], task['project_id'], 'artifact.export', {'task_id': task_id, 'format': format})
        if format == 'json':
            content, media = packed(task), 'application/json'
        elif format == 'csv':
            def safe(x):
                value = str(x)
                return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['candidate_id', 'name', 'score', 'matched_skills', 'missing_skills', 'approved'])
            for c in task['result']['candidates']:
                writer.writerow([safe(c['candidate_id']), safe(c['name']), c['score'], safe(', '.join(c['matched_skills'])), safe(', '.join(c['missing_skills'])), c['candidate_id'] in task['approved_ids']])
            content, media = '\ufeff' + buf.getvalue(), 'text/csv'
        else:
            lines = ['# Результат скрининга', '', f"Задание: {task_id}", f"Статус: {task['status']}", '', 'Список требует проверки рекрутером', '']
            for c in task['result']['candidates']:
                lines += [f"## {c['name']} ({c['score']}/100)", c['summary'], '', 'Подтверждено: ' + ', '.join(c['matched_skills']), 'Не подтверждено: ' + ', '.join(c['missing_skills'])]
                lines += [f"- {e['source']}: {e['quote']}" for e in c['evidence']]
                lines += ['']
            content, media = '\n'.join(lines), 'text/markdown'
        return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="screening-{task_id}.{format}"'})

    @app.get('/api/audit')
    def audit(account=Depends(user)):
        require(store, account, {'recruiter', 'admin', 'auditor'})
        return [e for e in store.events() if e['tenant'] == account['tenant_id'] and (not e['project'] or e['project'] in account['projects'])][-1000:]

    @app.get('/api/admin')
    def admin(account=Depends(user)):
        require(store, account, {'admin'})
        values = [t for t in store.list('task') if scope(account, t)]
        ordered = sorted(durations)
        return {'tasks': len(values), 'active': len(service.active), 'queue': sum(t['status'] == 'created' for t in values),
                'states': {state: sum(t['status'] == state for t in values) for state in sorted({t['status'] for t in values})},
                'api': {'requests': requests[0], 'errors': errors[0], 'p95_ms': ordered[int(.95 * (len(ordered) - 1))] if ordered else 0},
                'audit': store.verify_audit(), 'workers': service.workers,
                'models': {'semantic': bool(service.model_path), 'llm': bool(service.llm_path)},
                'versions': {'app': '1.0.0', 'policy': 'hr-1', 'prompt': 'facts-1'}}

    @app.get('/metrics')
    def metrics(account=Depends(user)):
        require(store, account, {'admin'})
        return Response(f'hr_api_requests_total {requests[0]}\nhr_api_errors_total {errors[0]}\nhr_workers_active {len(service.active)}\n', media_type='text/plain')

    static = Path(__file__).with_name('static')
    static.mkdir(exist_ok=True)
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/')
    def index():
        return FileResponse(static / 'index.html')

    return app
