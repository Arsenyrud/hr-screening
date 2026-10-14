const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(resolve(__dirname, '../hr_screening/static/app.js'), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(setImmediate);

function functionSource(name) {
  const start = source.indexOf(`  async function ${name}(`);
  assert.notEqual(start, -1, `Actual function ${name} exists`);
  const end = source.indexOf('\n  }', start);
  return source.slice(start, end + 4);
}

function element() {
  return { disabled: false, hidden: false, textContent: '', innerHTML: '', isConnected: true, setAttribute() {}, removeAttribute() {}, focus() {}, close() { this.closes = (this.closes || 0) + 1; } };
}

function harness(name, overrides = {}) {
  const nodes = new Map(['#resource-error', '#entry-dialog', '#dialog-title', '#resume-file'].map((key) => [key, element()]));
  const calls = { toasts: [], sources: [], mounts: [], loads: 0, sync: 0, logout: 0 };
  const button = element();
  const state = { token: 'token-a', user: { role: 'recruiter', tenant_id: 'agency-a' }, resumes: [], loaded: new Set(), busy: false, selectedId: 'task-a', selectedTask: { id: 'task-a' }, tasks: [], selectedCandidates: new Set(), approvalComment: '', tab: 'resumes' };
  const drawer = { stack: [], epoch: 0 };
  class FormDataStub {
    constructor(form) { this.values = form ? Object.entries(form.values) : []; }
    append(key, value) { this.values.push([key, value]); }
    [Symbol.iterator]() { return this.values[Symbol.iterator](); }
  }
  const context = vm.createContext({ state, drawer, Headers, FormData: FormDataStub, document: { createElement: element }, pdfFiles: new WeakMap(),
    $: (selector) => selector === 'button[type="submit"]' ? button : nodes.get(selector), arr: (value) => Array.isArray(value) ? value : [],
    isRecruiter: () => state.user?.role === 'recruiter', validatePdfFile: () => '', skeleton: () => 'loading', esc: String,
    openDrawer: (entry) => { drawer.stack = [entry]; drawer.epoch++; }, pushDrawer: (entry) => { drawer.stack.push(entry); drawer.epoch++; },
    sourceScreen: (record) => ({ record }), mountDrawer: (entry) => calls.mounts.push(entry), openSource: (...args) => calls.sources.push(args),
    toast: (...args) => calls.toasts.push(args), logout: () => { calls.logout++; state.token = ''; state.user = null; },
    loadTab: async () => { calls.loads++; }, saveDraft() {}, writeRoute() {}, setTask() {}, patchTasks() {}, syncSelection: () => calls.sync++,
    loadController: null, pollController: null, loadEpoch: 0, taskEpoch: 0, ...overrides });
  vm.runInContext(`${functionSource(name)}\nthis.target = ${name};`, context);
  const switchSession = () => {
    state.token = 'token-b'; state.user = { role: 'recruiter', tenant_id: 'agency-b' }; state.busy = true;
    state.resumes = [{ id: 'resume-b', text: 'Tenant B data' }]; state.loaded = new Set(['tasks']); drawer.stack = []; drawer.epoch++;
    nodes.set('#resource-error', { ...element(), textContent: 'New dialog message', hidden: true });
  };
  const form = { dataset: { kind: 'resumes', mode: 'pdf' }, values: { name: 'Candidate A', email: '', project_id: 'alpha' }, reportValidity: () => true, isConnected: true };
  context.pdfFiles.set(form, { name: 'resume.pdf', size: 100, type: 'application/pdf' });
  return { context, state, drawer, calls, nodes, button, form, switchSession };
}

test('old PDF upload response cannot insert data or open a drawer in another session', async () => {
  const request = deferred();
  const h = harness('submitResource', { api: () => request.promise });
  const pending = h.context.target(h.form);
  h.switchSession();
  request.resolve({ id: 'resume-a', name: 'Tenant A', text: 'Private A' });
  await pending;
  assert.deepEqual(h.state.resumes.map((record) => record.id), ['resume-b']);
  assert.equal(h.calls.loads, 0); assert.equal(h.calls.sources.length, 0); assert.equal(h.calls.toasts.length, 0);
  assert.equal(h.nodes.get('#entry-dialog').closes || 0, 0); assert.equal(h.state.busy, true); assert.equal(h.button.disabled, true);
});

test('session switch during upload refresh prevents later PDF insertion and notifications', async () => {
  const refresh = deferred();
  const h = harness('submitResource', { api: async () => ({ id: 'resume-a', name: 'Tenant A' }), loadTab: () => refresh.promise });
  const pending = h.context.target(h.form);
  await tick(); h.switchSession(); refresh.resolve(); await pending;
  assert.deepEqual(h.state.resumes.map((record) => record.id), ['resume-b']);
  assert.equal(h.calls.sources.length, 0); assert.equal(h.calls.toasts.length, 0); assert.equal(h.state.busy, true);
});

test('failed old upload cannot overwrite a new dialog error or busy state', async () => {
  const request = deferred();
  const h = harness('submitResource', { api: () => request.promise });
  const pending = h.context.target(h.form);
  h.switchSession(); request.reject(new Error('Old upload error')); await pending;
  assert.equal(h.nodes.get('#resource-error').textContent, 'New dialog message');
  assert.equal(h.nodes.get('#resource-error').hidden, true); assert.equal(h.state.busy, true); assert.equal(h.button.disabled, true);
});

test('old source list cannot replace another tenant cache before drawer guards', async () => {
  const request = deferred();
  const h = harness('openSource', { api: () => request.promise });
  const pending = h.context.target('resume-a');
  h.switchSession(); request.resolve([{ id: 'resume-a', name: 'Tenant A', text: 'Private A' }]); await pending;
  assert.deepEqual(h.state.resumes.map((record) => record.id), ['resume-b']);
  assert.equal(h.state.loaded.has('resumes'), false); assert.equal(h.calls.mounts.length, 0);
});

test('late task snapshot response cannot mount in another session', async () => {
  const request = deferred();
  const h = harness('openSource', { api: () => request.promise });
  h.drawer.stack = [{ kind: 'candidate', taskId: 'task-a' }];
  const pending = h.context.target('resume-a', true);
  h.switchSession(); request.resolve({ id: 'resume-a', name: 'Tenant A' }); await pending;
  assert.equal(h.calls.mounts.length, 0); assert.deepEqual(h.state.resumes.map((record) => record.id), ['resume-b']);
});

test('401 from an old API request cannot log out a new session', async () => {
  const request = deferred();
  const h = harness('api', { fetch: () => request.promise });
  const pending = h.context.target('/api/resumes');
  h.switchSession(); request.resolve({ status: 401, ok: false, json: async () => ({ detail: 'Old session expired' }) });
  await assert.rejects(pending, /Old session expired/);
  assert.equal(h.calls.logout, 0); assert.equal(h.state.token, 'token-b');
});

test('401 from the current API request still expires its own session', async () => {
  const h = harness('api', { fetch: async () => ({ status: 401, ok: false, json: async () => ({ detail: 'Expired' }) }) });
  await assert.rejects(h.context.target('/api/resumes'), /Expired/);
  assert.equal(h.calls.logout, 1); assert.equal(h.state.token, '');
});

test('old download 401 cannot log out, notify, or reset a new session button', async () => {
  const request = deferred();
  const h = harness('download', { fetch: () => request.promise });
  const pending = h.context.target('/api/resumes/resume-a/pdf', 'resume.pdf', h.button);
  h.switchSession(); request.resolve({ status: 401, ok: false, json: async () => ({ detail: 'Old session expired' }) }); await pending;
  assert.equal(h.calls.logout, 0); assert.equal(h.calls.toasts.length, 0); assert.equal(h.button.disabled, true);
});

test('download error decoded after a session switch is not shown to the new user', async () => {
  const details = deferred();
  const h = harness('download', { fetch: async () => ({ status: 500, ok: false, json: () => details.promise }) });
  const pending = h.context.target('/api/resumes/resume-a/pdf', 'resume.pdf', h.button);
  await tick(); h.switchSession(); details.resolve({ detail: 'Tenant A server error' }); await pending;
  assert.equal(h.calls.toasts.length, 0); assert.equal(h.button.disabled, true);
});

for (const rejected of [false, true]) test(`old task action ${rejected ? 'error' : 'success'} cannot clear a new operation busy state`, async () => {
  const request = deferred();
  const h = harness('taskAction', { api: () => request.promise });
  const pending = h.context.target('pause', h.button);
  h.switchSession();
  rejected ? request.reject(new Error('Old operation error')) : request.resolve({ id: 'task-a', status: 'paused' });
  await pending;
  assert.equal(h.state.busy, true); assert.equal(h.calls.sync, 0); assert.equal(h.calls.toasts.length, 0); assert.equal(h.button.disabled, true);
});
