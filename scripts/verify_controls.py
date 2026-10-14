"""Проверка прав, восстановления и резервной копии."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_screening.api import create_app
from hr_screening.seed import seed
from hr_screening.service import ScreeningService
from hr_screening.store import Store


def save(name, value):
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence' / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def controls():
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(str(Path(folder) / 'security.sqlite'), start_worker=False)
        seed(app.state.store)
        with TestClient(app) as c:
            def login(username, password):
                return {'Authorization': 'Bearer ' + c.post('/api/login', json={'username': username, 'password': password}).json()['token']}
            recruiter = login('recruiter', 'Recruiter-2026!')
            client = login('client', 'Client-2026!')
            auditor = login('auditor', 'Auditor-2026!')
            checks = []
            def check(name, observed, expected):
                checks.append({'name': name, 'observed': observed, 'expected': expected, 'passed': observed == expected})
            check('unauthenticated_resume_read', c.get('/api/resumes').status_code, 401)
            check('client_resume_read', c.get('/api/resumes', headers=client).status_code, 403)
            check('auditor_resume_read', c.get('/api/resumes', headers=auditor).status_code, 403)
            check('foreign_project_write', c.post('/api/resumes', headers=recruiter, json={'name': 'Тест', 'text': 'Python developer', 'project_id': 'beta'}).status_code, 403)
            foreign = next(v for v in app.state.store.list('vacancy') if v['tenant_id'] == 'agency-b')
            check('foreign_tenant_task', c.post('/api/tasks', headers=recruiter, json={'vacancy_id': foreign['id']}).status_code, 404)
            task = c.post('/api/tasks', headers=recruiter, json={'vacancy_id': 'v-python'}).json()
            check('draft_hidden_from_client', c.get('/api/tasks/' + task['id'], headers=client).status_code, 404)
            app.state.service.run_task(task['id'])
            result = app.state.store.get('task', task['id'])['result']
            candidate = next(r for r in app.state.store.list('resume') if 'ignore previous' in r['text'].lower())
            from hr_screening.engine import screen
            injected = screen(app.state.store.get('vacancy', 'v-python'), [candidate])
            check('prompt_injection_is_inert', any('инструкц' in item for row in injected['candidates'] for item in row['concerns']), True)
            check('audit_chain', app.state.store.verify_audit()['valid'], True)
            denied = sum(e['action'] == 'access.denied' for e in app.state.store.events())
            check('denied_operations_audited', denied >= 5, True)
            save('security.json', {'checks': checks, 'all_passed': all(c['passed'] for c in checks),
                                   'scope': 'API RBAC/project/tenant, inert text, audit; no OS network isolation claim'})


def recovery():
    with tempfile.TemporaryDirectory() as folder:
        db = Path(folder) / 'state.sqlite'
        store = Store(db)
        seed(store)
        service = ScreeningService(store)
        task = service.create(store.get('user', 'recruiter'), {'vacancy_id': 'v-python'}, None)
        store.close()
        child_code = '''import os,sys
from hr_screening.store import Store
s=Store(sys.argv[1]);t=s.get('task',sys.argv[2]);v=t['vacancy']
r=[x for x in s.list('resume') if x['tenant_id']==v['tenant_id'] and x['project_id']==v['project_id']]
s.put('snapshot',{'id':t['id'],'resumes':r})
s.update('task',t['id'],lambda x:{**x,'status':'running','stage':2,'checkpoint':{'vacancy':v,'resume_snapshot':t['id'],'resume_ids':[y['id'] for y in r]}})
os._exit(17)
'''
        crash = subprocess.run([sys.executable, '-c', child_code, str(db), task['id']], cwd=ROOT)
        started = time.perf_counter()
        store = Store(db)
        before = store.get('task', task['id'])
        restored = ScreeningService(store)
        restored.recover()
        recovered = store.get('task', task['id'])
        restored.run_task(task['id'])
        final = store.get('task', task['id'])
        recovery_seconds = time.perf_counter() - started
        backup = Path(folder) / 'backup.sqlite'
        started = time.perf_counter()
        store.backup(backup)
        copied = Store(backup)
        valid = copied.verify_audit()['valid']
        same = copied.get('task', task['id'])['result'] == final['result']
        elapsed = time.perf_counter() - started
        copied.close()
        save('recovery.json', {'child_exit_code': crash.returncode, 'status_at_crash': before['status'], 'checkpoint_stage': before['stage'],
                               'status_after_recovery': recovered['status'], 'final_status': final['status'],
                               'candidates': len(final['result']['candidates']), 'recovery_seconds': recovery_seconds,
                               'backup_restore_seconds': elapsed, 'audit_valid_after_restore': valid, 'result_preserved': same,
                               'passed': crash.returncode == 17 and final['status'] == 'waiting' and valid and same})
        store.close()


if __name__ == '__main__':
    controls()
    recovery()
    print('Протоколы безопасности и восстановления сохранены')
