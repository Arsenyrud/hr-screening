"""Очередь, этапы и контроль выполнения."""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from fastapi import HTTPException

from .security import require, scope
from .store import now


TERMINAL = {'completed', 'error', 'destroyed'}
STAGES = ['vacancy.normalize', 'resumes.read', 'candidates.compare', 'artifact.prepare']


class Interrupted(Exception):
    pass


class ScreeningService:
    def __init__(self, store, model_path=None, workers=4, llm_path=None):
        self.store, self.model_path = store, model_path
        self.workers, self.llm_path = workers, llm_path
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.active = set()
        self.pool = None
        self.thread = None
        self.llm = None
        self.compute = None

    def event(self, task, action, detail=None, actor=None, role=None):
        self.store.audit(actor or task['owner_id'], role or ('worker' if not actor else task.get('owner_role', 'recruiter')),
                         task['tenant_id'], task['project_id'], action,
                         {'task_id': task['id'], 'initiator': task['owner_id'], 'component': 'orchestrator', **(detail or {})})

    def recover(self):
        for task in self.store.list('task'):
            if task['status'] in {'initializing', 'ready', 'running'}:
                task = self.store.update('task', task['id'], lambda t: {**t, 'status': 'created', 'generation': t['generation'] + 1, 'running_since': None, 'updated_at': now()})
                self.event(task, 'task.recovered', {'stage': task['stage']})

    def start(self):
        from .compute import ComputePool
        self.recover()
        self.compute = ComputePool(workers=1 if self.model_path or self.llm_path else min(4, self.workers))
        self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='screening')
        self.thread = threading.Thread(target=self.dispatch, daemon=True)
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)
        if self.compute:
            self.compute.close()

    def dispatch(self):
        while not self.stop.wait(.1):
            with self.guard:
                available = self.workers - len(self.active)
                if available <= 0:
                    continue
                tasks = [t for t in self.store.list('task', status='created') if t['id'] not in self.active]
                for task in tasks[:available]:
                    self.active.add(task['id'])
                    self.pool.submit(self.run_task, task['id'])

    def create(self, user, body, key):
        require(self.store, user, {'recruiter'})
        vacancy = self.store.get('vacancy', body['vacancy_id'])
        if not vacancy or not scope(user, vacancy):
            self.store.audit(user['id'], user['role'], user['tenant_id'], None, 'access.denied', {'operation': 'task.create'})
            raise HTTPException(404, 'Вакансия не найдена')
        with self.guard:
            if key:
                prior = next((t for t in self.store.list('task') if t['owner_id'] == user['id'] and t.get('idempotency_key') == key), None)
                if prior:
                    if prior['vacancy_id'] != vacancy['id'] or prior.get('requested_limits', {}) != body.get('limits', {}):
                        raise HTTPException(409, 'Ключ уже использован с другими параметрами')
                    return prior
            pending = [t for t in self.store.list('task') if t['status'] not in TERMINAL]
            if len(pending) >= 100:
                raise HTTPException(429, 'Очередь заполнена')
            limits = {'max_seconds': 180, 'max_candidates': 500, 'max_tool_calls': 12, **body.get('limits', {})}
            stamp = now()
            task = {'id': uuid.uuid4().hex, 'tenant_id': vacancy['tenant_id'], 'project_id': vacancy['project_id'],
                    'owner_id': user['id'], 'owner_role': user['role'], 'vacancy_id': vacancy['id'], 'vacancy': vacancy,
                    'status': 'created', 'stage': 0, 'generation': 0, 'checkpoint': {}, 'result': None, 'error': None,
                    'created_at': stamp, 'updated_at': stamp, 'limits': limits, 'tool_calls': 0,
                    'idempotency_key': key, 'requested_limits': body.get('limits', {}),
                    'used_seconds': 0, 'running_since': None, 'deadline_at': None, 'approved_ids': [], 'approval_comment': None,
                    'versions': {'app': '1.0.0', 'policy': 'hr-1', 'prompt': 'facts-1'}}
            with self.store.transaction():
                self.store.put('task', task)
                self.event(task, 'task.created', {'versions': task['versions']}, user['id'], user['role'])
            return task

    def control(self, user, task, action, body=None):
        require(self.store, user, {'admin', 'recruiter'}, task)
        if action != 'cancel' and user['role'] != 'recruiter':
            require(self.store, user, {'recruiter'})
        choices = {'pause': ({'created', 'initializing', 'ready', 'running'}, 'paused'),
                   'resume': ({'paused'}, 'created'), 'cancel': ({'created', 'initializing', 'ready', 'running', 'paused', 'waiting', 'error'}, 'destroyed'),
                   'approve': ({'waiting'}, 'completed')}
        allowed, target = choices[action]

        def change(t):
            if t['status'] not in allowed:
                raise HTTPException(409, 'Переход из текущего состояния запрещен')
            if t.get('running_since'):
                t['used_seconds'] = t.get('used_seconds', 0) + max(0, time.time() - t['running_since'])
                t['running_since'] = None
            if action == 'approve':
                ids = list(dict.fromkeys((body or {}).get('candidate_ids', [])))
                valid = {c['candidate_id'] for c in t['result']['candidates']}
                if not ids or not set(ids) <= valid:
                    raise HTTPException(422, 'Выберите кандидатов из результата задания')
                t.update(approved_ids=ids, approval_comment=(body or {}).get('comment', ''), approved_by=user['id'], approved_at=now())
            return {**t, 'status': target, 'generation': t['generation'] + 1, 'updated_at': now()}

        with self.store.transaction():
            result = self.store.update('task', task['id'], change)
            self.event(result, 'task.' + action, {'approved_ids': result['approved_ids'] if action == 'approve' else []}, user['id'], user['role'])
        return result

    def run_task(self, task_id):
        started = time.monotonic()
        generation = None
        try:
            task = self.store.get('task', task_id)
            if not task or task['status'] != 'created':
                return
            generation = task['generation']
            deadline = task.get('deadline_at') or time.time() + task['limits']['max_seconds']

            def check():
                current = self.store.get('task', task_id)
                if self.stop.is_set() or current['generation'] != generation or current['status'] in TERMINAL | {'paused'}:
                    raise Interrupted()
                if time.time() > deadline:
                    raise TimeoutError('quota: превышено время выполнения')
                return current

            def write(**updates):
                def change(t):
                    if t['generation'] != generation or t['status'] in TERMINAL | {'paused'}:
                        raise Interrupted()
                    return {**t, **updates, 'updated_at': now()}
                return self.store.update('task', task_id, change)

            write(status='initializing', running_since=time.time(), deadline_at=deadline)
            self.event(task, 'worker.initialized')
            write(status='ready')
            write(status='running', started_at=now())
            for index in range(task['stage'], len(STAGES)):
                current = check()
                if current['tool_calls'] >= task['limits']['max_tool_calls']:
                    raise RuntimeError('quota: превышено число вызовов инструментов')
                checkpoint = current['checkpoint']
                self.event(task, 'stage.started', {'stage': STAGES[index]})
                if index == 0:
                    checkpoint['vacancy'] = task['vacancy']
                elif index == 1:
                    resumes = [r for r in self.store.list('resume') if r['tenant_id'] == task['tenant_id'] and r['project_id'] == task['project_id']]
                    if len(resumes) > task['limits']['max_candidates']:
                        raise RuntimeError('quota: превышено число кандидатов; сузьте проект')
                    self.store.put('snapshot', {'id': task_id, 'resumes': resumes})
                    checkpoint['resume_snapshot'] = task_id
                    checkpoint['resume_ids'] = [r['id'] for r in resumes]
                    self.event(task, 'tool.resumes.read', {'count': len(resumes), 'ids': [r['id'] for r in resumes]})
                elif index == 2:
                    snapshot = self.store.get('snapshot', checkpoint['resume_snapshot'])
                    if not snapshot:
                        raise RuntimeError('Снимок резюме недоступен')
                    if self.compute:
                        future = self.compute.submit(checkpoint['vacancy'], snapshot['resumes'], self.model_path, self.llm_path, max(.01, deadline - time.time()))
                        try:
                            while True:
                                check()
                                try:
                                    checkpoint['result'] = future.result(timeout=.1)
                                    break
                                except FutureTimeout:
                                    continue
                        finally:
                            if not future.done():
                                future.cancel_event.set()
                                future.cancel()
                    else:
                        from .compute import execute
                        checkpoint['result'] = execute(checkpoint['vacancy'], snapshot['resumes'], self.model_path, self.llm_path, max(.01, deadline - time.time()))
                elif index == 3:
                    checkpoint['result']['provenance'] = {'vacancy_id': task['vacancy_id'], 'resume_ids': checkpoint['resume_ids'],
                                                          'versions': task['versions'], 'requires_human_review': True}
                check()
                write(checkpoint=checkpoint, stage=index + 1, tool_calls=current['tool_calls'] + 1,
                      used_seconds=task.get('used_seconds', 0) + time.monotonic() - started, running_since=time.time())
                self.event(task, 'stage.completed', {'stage': STAGES[index]})
            current = check()
            write(status='waiting', result=current['checkpoint']['result'], duration_seconds=round(time.monotonic() - started, 4),
                  used_seconds=task.get('used_seconds', 0) + time.monotonic() - started, running_since=None)
            self.event(task, 'task.waiting')
        except Interrupted:
            pass
        except Exception as exc:
            task = self.store.get('task', task_id)
            if task and task['generation'] == generation and task['status'] not in TERMINAL | {'paused'}:
                error = str(exc) if isinstance(exc, (RuntimeError, TimeoutError, ValueError)) else type(exc).__name__ + ': ошибка этапа'
                def fail(t):
                    if t['generation'] != generation or t['status'] in TERMINAL | {'paused'}:
                        return t
                    return {**t, 'status': 'error', 'error': error[:500], 'updated_at': now(), 'running_since': None,
                            'used_seconds': t.get('used_seconds', 0) + max(0, time.time() - (t.get('running_since') or time.time()))}
                with self.store.transaction():
                    result = self.store.update('task', task_id, fail)
                    if result['status'] == 'error':
                        self.event(task, 'task.error', {'error': error[:500]})
        finally:
            with self.guard:
                self.active.discard(task_id)
