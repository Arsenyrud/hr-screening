"""Нагрузка на настоящий HTTP сервер в loopback."""

import copy
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_screening.seed import seed
from hr_screening.store import Store


def quantile(values, fraction):
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


def profile(pool_size, concurrent):
    with tempfile.TemporaryDirectory() as work:
        store = Store(Path(work) / 'load.sqlite')
        data = seed(store)
        originals = [r for r in data['resumes'] if r['tenant_id'] == 'agency-a' and r['project_id'] == 'alpha']
        for index in range(pool_size - len(originals)):
            record = copy.deepcopy(originals[index % len(originals)])
            record['id'], record['email'] = f'load-{index:04}', f'load{index}@example.invalid'
            store.put('resume', record)
        store.close()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in {'HR_MODEL_PATH', 'HR_LLM_PATH'}}
        env.update(HR_DB=str(Path(work) / 'load.sqlite'), HR_WORKERS=str(concurrent), HF_HUB_OFFLINE='1')
        with open(Path(work) / 'server.log', 'w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'hr_screening.api:create_app', '--factory', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=120) as client:
                    for _ in range(100):
                        try:
                            if client.get('/health').status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(.1)
                    login = client.post('/api/login', json={'username': 'recruiter', 'password': 'Recruiter-2026!'}).json()
                    client.headers['Authorization'] = 'Bearer ' + login['token']
                    created, api_ms, statuses = [], [], []

                    def create(index):
                        started = time.perf_counter()
                        response = client.post('/api/tasks', json={'vacancy_id': 'v-python'})
                        return response.json(), (time.perf_counter() - started) * 1000, response.status_code

                    started = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=concurrent) as executor:
                        for task, latency, status in executor.map(create, range(concurrent)):
                            created.append(task)
                            api_ms.append(latency)
                            statuses.append(status)

                    def read(index):
                        before = time.perf_counter()
                        response = client.get('/api/tasks/' + created[index % len(created)]['id'])
                        return (time.perf_counter() - before) * 1000, response.status_code

                    with ThreadPoolExecutor(max_workers=8) as executor:
                        for latency, status in executor.map(read, range(200)):
                            api_ms.append(latency)
                            statuses.append(status)
                    deadline = time.monotonic() + 120
                    while True:
                        tasks = [client.get('/api/tasks/' + t['id']).json() for t in created]
                        if all(t['status'] in {'waiting', 'error'} for t in tasks):
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError('load profile did not finish')
                        time.sleep(.05)
                    elapsed = time.perf_counter() - started
                    task_ms = [t.get('duration_seconds', 0) * 1000 for t in tasks]
                    for _ in range(max(0, 20 - concurrent)):
                        task = client.post('/api/tasks', json={'vacancy_id': 'v-python'}).json()
                        client.post('/api/tasks/' + task['id'] + '/pause')
                    active = [t for t in client.get('/api/tasks').json() if t['status'] in {'waiting', 'paused', 'running', 'created', 'ready', 'initializing'}]
                    return {'mode': 'baseline', 'pool_size': pool_size, 'concurrent_tasks': concurrent, 'workers': concurrent,
                            'api_samples': len(api_ms), 'api_latencies_ms': api_ms, 'http_statuses': statuses,
                            'api_p95_ms': quantile(api_ms, .95), 'api_p99_ms': quantile(api_ms, .99),
                            'api_error_fraction': sum(s >= 500 for s in statuses) / len(statuses),
                            'create_p95_ms': quantile(api_ms[:concurrent], .95), 'task_p95_ms': quantile(task_ms, .95),
                            'task_p99_ms': quantile(task_ms, .99), 'elapsed_seconds': elapsed, 'throughput_tasks_per_second': concurrent / elapsed,
                            'statuses': [t['status'] for t in tasks], 'active_executors_observed': len(active),
                            'limitations': 'Synthetic duplicated texts, baseline, loopback HTTP, no LLM throughput claim'}
            finally:
                server.terminate()
                server.wait(timeout=15)


if __name__ == '__main__':
    results = [profile(size, count) for size, count in [(30, 1), (100, 8), (500, 12)]]
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence/load_test.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    for result in results:
        print({k: result[k] for k in ['pool_size', 'concurrent_tasks', 'api_p95_ms', 'api_error_fraction', 'statuses', 'active_executors_observed']})
