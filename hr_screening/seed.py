"""Синтетические данные для демонстрации."""

import argparse
import base64
import json
from pathlib import Path

from .security import password_hash
from .store import Store


def seed(store, pdfs=False):
    data = json.loads((Path(__file__).resolve().parents[1] / 'data/demo.json').read_text())
    for kind, values in [('vacancy', data['vacancies']), ('resume', data['resumes'])]:
        for item in values:
            if not store.get(kind, item['id']):
                store.put(kind, item)
    if pdfs:
        from .documents import parse_pdf
        root = Path(__file__).resolve().parents[1] / 'data/resumes'
        for item in data['resumes']:
            path = root / f"{item['id']}.pdf"
            payload = path.read_bytes()
            parsed = parse_pdf(payload)
            record = store.get('resume', item['id'])
            record.update(text=parsed.pop('text'), document={'format': 'pdf', 'filename': path.name, **parsed})
            store.put('resume', record)
            store.put('attachment', {'id': item['id'], 'tenant_id': item['tenant_id'], 'project_id': item['project_id'],
                                     'format': 'pdf', 'data_b64': base64.b64encode(payload).decode('ascii')})
    for username, role, password, tenant, projects in [
        ('recruiter', 'recruiter', 'Recruiter-2026!', 'agency-a', ['alpha']),
        ('client', 'client', 'Client-2026!', 'agency-a', ['alpha']),
        ('admin', 'admin', 'Admin-2026!', 'agency-a', ['alpha', 'beta']),
        ('auditor', 'auditor', 'Auditor-2026!', 'agency-a', ['alpha', 'beta']),
        ('recruiter-b', 'recruiter', 'RecruiterB-2026!', 'agency-b', ['alpha']),
    ]:
        if not store.get('user', username):
            store.put('user', {'id': username, 'username': username, 'role': role, 'tenant_id': tenant,
                               'projects': projects, 'password_hash': password_hash(password)})
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Создать демонстрационную базу')
    parser.add_argument('--db', default='runtime/hr.sqlite')
    parser.add_argument('--pdf', action='store_true', help='Загрузить синтетические PDF вместо текстовых fixtures')
    args = parser.parse_args()
    with_store = Store(args.db)
    seed(with_store, pdfs=args.pdf)
    with_store.close()
    print('Демонстрационная база готова')
