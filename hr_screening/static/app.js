(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const arr = (value) => Array.isArray(value) ? value : [];
  const shortId = (value) => String(value ?? '').slice(0, 8);
  const initials = (value) => String(value || '?').trim().split(/\s+/).slice(0, 2).map((part) => part[0] || '').join('').toUpperCase();
  const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const dateValue = (value) => new Date(typeof value === 'number' ? value * (value < 1e12 ? 1000 : 1) : value);
  const formatDate = (value) => !value ? '-' : Number.isNaN(dateValue(value).getTime()) ? String(value) : new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(dateValue(value));
  const icons = {
    tasks: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v4H9zM9 12h6m-6 4h4"/>',
    vacancies: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4h8v3M3 12h18m-11-1v3h4v-3"/>',
    resumes: '<circle cx="8" cy="7" r="3"/><path d="M3 20v-2a5 5 0 0 1 10 0v2H3zm14-16h4m-4 5h4m-4 5h4"/>',
    audit: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    admin: '<path d="M4 20V10m8 10V4m8 16v-7M1 10h6m2-6h6m2 9h6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>', check: '<path d="m5 12 4 4L19 6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-11v1"/>', pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="m8 4 12 8-12 8V4Z"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>', arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    upload: '<path d="M12 16V3M7 8l5-5 5 5M4 16v5h16v-5"/>'
  };
  const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.tasks}</svg>`;
  const roles = { recruiter: 'Рекрутер', client: 'Заказчик', admin: 'Администратор', auditor: 'Аудитор' };
  const tabs = {
    tasks: { title: 'Задания' },
    vacancies: { title: 'Вакансии' },
    resumes: { title: 'База резюме' },
    audit: { title: 'Журнал аудита' },
    admin: { title: 'Эксплуатация' }
  };
  const roleTabs = { recruiter: ['tasks', 'vacancies', 'resumes'], client: ['tasks'], admin: ['admin', 'tasks', 'audit'], auditor: ['audit'] };
  const statusText = { created: 'В очереди', initializing: 'Подготовка', ready: 'Готово к запуску', running: 'В работе', waiting: 'На проверке', paused: 'Приостановлено', completed: 'Утверждено', error: 'Ошибка', destroyed: 'Отменено' };
  const activeStatuses = new Set(['created', 'initializing', 'ready', 'running']);
  const filters = [['all', 'Все'], ['waiting', 'На проверке'], ['completed', 'Утверждены']];
  const evidenceLabels = { stated: 'Указано в резюме', conflicting: 'Есть противоречие', negated: 'Навык отрицается' };
  const eventLabels = { 'task.created': 'Задание создано', 'worker.initialized': 'Исполнитель подготовлен', 'stage.started': 'Этап начат', 'stage.completed': 'Этап завершен', 'task.waiting': 'Передано на проверку', 'task.approve': 'Список утвержден', 'task.pause': 'Задание приостановлено', 'task.resume': 'Обработка продолжена', 'task.cancel': 'Задание отменено', 'task.error': 'Ошибка обработки', 'task.recovered': 'Задание восстановлено', 'tool.resumes.read': 'Прочитаны доступные резюме', 'artifact.export': 'Результат экспортирован' };
  const state = { token: '', user: null, tab: 'tasks', tasks: [], vacancies: [], resumes: [], audit: [], admin: {}, selectedId: '', selectedTask: null, selectedCandidates: new Set(), approvalComment: '', mobileDetail: false, loaded: new Set(), views: {}, drafts: new Map(), loading: false, busy: false, polling: false };
  const auditActor = (event) => event.role === 'worker' ? `Система (инициатор: ${event.detail?.initiator || event.actor || 'не указан'})` : event.actor || 'Система';
  const pdfFiles = new WeakMap();
  const drawer = { stack: [], opener: null, epoch: 0, timer: null };
  let loadController, taskController, pollController, loadEpoch = 0, taskEpoch = 0, pollTimer, toastTimer, listScroll = 0;
  const storage = { get() { try { return sessionStorage.getItem('hr-screening-token') || ''; } catch { return ''; } }, set(token) { try { token ? sessionStorage.setItem('hr-screening-token', token) : sessionStorage.removeItem('hr-screening-token'); } catch {} } };
  const isRecruiter = () => state.user?.role === 'recruiter';
  const canManage = () => ['recruiter', 'admin'].includes(state.user?.role);
  const canApprove = (task = state.selectedTask) => isRecruiter() && task?.status === 'waiting';
  const view = (tab = state.tab) => state.views[tab] ||= { query: '', status: 'all' };
  const projects = () => arr(state.user?.projects).map((item) => typeof item === 'string' ? { id: item, name: item } : { id: item.id || item.project_id, name: item.name || item.title || item.id || item.project_id }).filter((item) => item.id);
  const vacancyTitle = (task) => task.vacancy_title || task.vacancy?.title || task.result?.normalized_vacancy?.title || state.vacancies.find((item) => item.id === task.vacancy_id)?.title || `Вакансия ${shortId(task.vacancy_id)}`;
  const badge = (status) => `<span class="badge ${Object.hasOwn(statusText, status) ? status : ''}">${esc(statusText[status] || status || 'Нет статуса')}</span>`;
  const docMeta = (resume) => resume?.document || null;
  const pdfBadge = (resume) => docMeta(resume)?.format === 'pdf' ? `<span class="document-badge">PDF${docMeta(resume).pages ? ` · ${esc(docMeta(resume).pages)} стр.` : ''}</span>` : '';
  const empty = (title, text, kind = 'tasks') => `<div class="empty-state"><span class="empty-icon">${icon(kind)}</span><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
  const skeleton = () => '<div class="skeleton" role="status" aria-label="Загрузка данных"><span class="sr-only">Загрузка данных</span><i></i><i></i><i></i><i></i></div>';
  const setHTML = (element, html) => { if (element && element.innerHTML !== html) element.innerHTML = html; };

  async function api(path, options = {}) {
    const { anonymous = false, ...requestOptions } = options, requestToken = state.token;
    const headers = new Headers(requestOptions.headers || {});
    headers.set('Accept', 'application/json');
    if (requestToken && !anonymous) headers.set('Authorization', `Bearer ${requestToken}`);
    if (requestOptions.body && !(requestOptions.body instanceof FormData) && typeof requestOptions.body !== 'string') {
      requestOptions.body = JSON.stringify(requestOptions.body);
      headers.set('Content-Type', 'application/json');
    }
    let response;
    try { response = await fetch(path, { ...requestOptions, headers, cache: 'no-store' }); }
    catch (error) { if (error.name === 'AbortError') throw error; throw new Error('Нет связи с сервером. Проверьте подключение и повторите действие.'); }
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && !anonymous && requestToken === state.token) logout(false);
      const detail = data?.detail;
      const message = Array.isArray(detail) ? detail.map((item) => `${arr(item.loc).slice(1).join('.')}: ${item.msg}`).join('; ') : typeof detail === 'string' ? detail : '';
      throw new Error(message || ({ 401: 'Проверьте логин и пароль', 403: 'Для операции недостаточно прав', 404: 'Запись не найдена или недоступна в вашем проекте', 409: 'Состояние изменилось. Обновите данные', 413: 'Файл больше 5 МиБ. Выберите PDF меньшего размера', 422: 'Проверьте поля формы и формат PDF', 429: 'Слишком много запросов. Повторите немного позже' }[response.status]) || `Ошибка сервера: ${response.status}`);
    }
    return data;
  }

  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $('#toast-region').innerHTML = `<div class="toast${error ? ' error' : ''}">${icon(error ? 'info' : 'check')}<span>${esc(message)}</span><button type="button" class="icon-button" data-action="close-toast" aria-label="Закрыть уведомление">×</button></div>`;
    toastTimer = setTimeout(() => $('#toast-region').replaceChildren(), error ? 10000 : 6000);
  }

  function logout() {
    clearTimeout(pollTimer); loadController?.abort(); taskController?.abort(); pollController?.abort(); ++loadEpoch; ++taskEpoch;
    closeDrawer(true);
    if ($('#entry-dialog').open) $('#entry-dialog').close();
    Object.assign(state, { token: '', user: null, selectedId: '', selectedTask: null, tasks: [], vacancies: [], resumes: [], audit: [], admin: {}, views: {}, mobileDetail: false, busy: false });
    state.loaded.clear(); state.drafts.clear(); state.selectedCandidates.clear(); state.approvalComment = '';
    storage.set('');
    $('#app-view').hidden = true; $('#login-view').hidden = false; $('.skip-link').href = '#main';
    $('#login-form').reset(); $('#login-error').hidden = true; $('#view-content').replaceChildren(); $('#navigation').replaceChildren(); $('#page-actions').replaceChildren();
  }

  function routeValue(tab = state.tab, id = '') { return `#${tab}${tab === 'tasks' && id ? `/${encodeURIComponent(id)}` : ''}`; }
  function writeRoute(push = true) { const hash = routeValue(state.tab, state.tab === 'tasks' && state.mobileDetail ? state.selectedId : ''); if (location.hash !== hash) history[push ? 'pushState' : 'replaceState'](null, '', hash); }
  function readRoute() { const [tab, encoded] = location.hash.slice(1).split('/'); let id = ''; try { id = decodeURIComponent(encoded || ''); } catch {} return { tab, id }; }

  async function enterWorkspace(user) {
    state.user = user;
    const allowed = roleTabs[user.role] || [];
    const route = readRoute(); state.tab = allowed.includes(route.tab) ? route.tab : allowed[0];
    if (!state.tab) throw new Error('Для вашей роли не настроен рабочий раздел');
    state.selectedId = state.tab === 'tasks' ? route.id : ''; state.mobileDetail = !!state.selectedId;
    $('#login-view').hidden = true; $('#app-view').hidden = false; $('.skip-link').href = '#workspace-main';
    $('#profile-name').textContent = user.username; $('#profile-role').textContent = roles[user.role] || user.role;
    renderNavigation(); renderHeading();
    if (isRecruiter()) { const token = state.token; try { const data = await api('/api/vacancies'); if (token !== state.token) return; state.vacancies = arr(data); } catch (error) { if (!state.user || token !== state.token) return; toast(error.message, true); } }
    await loadTab(); schedulePoll();
  }

  function saveDraft() {
    if (state.selectedTask?.id) state.drafts.set(state.selectedTask.id, [...state.selectedCandidates]);
  }

  function setTask(task) {
    if (state.selectedTask?.id !== task.id) {
      saveDraft();
      state.selectedCandidates = new Set(state.drafts.get(task.id) || arr(task.approved_ids));
      state.approvalComment = '';
    }
    state.selectedTask = task; state.selectedId = task.id;
  }

  function renderNavigation() {
    setHTML($('#navigation'), (roleTabs[state.user.role] || []).map((tab) => `<button type="button" data-action="tab" data-tab="${tab}" class="${state.tab === tab ? 'active' : ''}"${state.tab === tab ? ' aria-current="page"' : ''}>${icon(tab)}<span>${tab === 'resumes' ? 'Резюме' : tabs[tab].title}</span>${tab === 'tasks' && state.tasks.some((task) => task.status === 'waiting') ? `<span class="nav-counter">${state.tasks.filter((task) => task.status === 'waiting').length}</span>` : ''}</button>`).join(''));
  }

  function renderHeading() {
    $('#page-title').textContent = tabs[state.tab].title;
    const label = { tasks: 'Новое сопоставление', vacancies: 'Добавить вакансию', resumes: 'Добавить резюме' }[state.tab];
    setHTML($('#page-actions'), isRecruiter() && label ? `<button type="button" class="button primary" data-action="create" aria-label="${esc(label)}">${icon('plus')}<span class="create-label">${esc(label)}</span></button>` : '');
  }

  function renderPage(animate = false) {
    renderHeading(); renderNavigation();
    const content = $('#view-content');
    content.classList.toggle('page-enter', animate && !reducedMotion());
    if (state.tab === 'tasks') content.innerHTML = renderTasks();
    else if (['vacancies', 'resumes'].includes(state.tab)) content.innerHTML = renderResources();
    else if (state.tab === 'audit') content.innerHTML = renderAudit(state.audit);
    else content.innerHTML = renderAdmin();
    if (state.tab === 'tasks') patchTaskDetail(true);
  }

  async function loadTab({ refresh = false } = {}) {
    const epoch = ++loadEpoch, token = state.token, tab = state.tab;
    loadController?.abort(); loadController = new AbortController();
    const signal = loadController.signal;
    state.loading = true; renderHeading();
    const cached = state.loaded.has(tab);
    if (!cached) $('#view-content').innerHTML = skeleton();
    else $('#view-content').setAttribute('aria-busy', 'true');
    try {
      const data = await api(`/api/${tab}`, { signal });
      if (epoch !== loadEpoch || token !== state.token || tab !== state.tab) return;
      state[tab] = tab === 'admin' ? data || {} : arr(data);
      if (tab === 'tasks') {
        if (state.selectedId && !state.tasks.some((task) => task.id === state.selectedId)) { state.selectedId = ''; state.selectedTask = null; state.mobileDetail = false; }
        if (!state.selectedId && state.tasks.length) state.selectedId = state.tasks[0].id;
        if (state.selectedId) setTask(state.tasks.find((task) => task.id === state.selectedId));
      }
      state.loaded.add(tab); state.loading = false;
      if (tab === 'tasks' && cached && $('#tasks-workspace')) patchTasks(); else renderPage(!refresh);
    } catch (error) {
      if (error.name === 'AbortError' || epoch !== loadEpoch || !state.user || token !== state.token || tab !== state.tab) return;
      if (!cached) $('#view-content').innerHTML = `<section class="panel region-error" role="alert"><h2>Не удалось загрузить данные</h2><p>${esc(error.message)}</p><button type="button" class="button" data-action="refresh">Повторить</button></section>`;
      else toast(error.message, true);
    } finally {
      if (epoch === loadEpoch) { state.loading = false; $('#view-content').removeAttribute('aria-busy'); if (state.user) renderHeading(); }
    }
  }

  function statusMatches(task, status) { return status === 'all' || task.status === status; }
  function filteredTasks() { return state.tasks.filter((task) => statusMatches(task, view('tasks').status) && `${vacancyTitle(task)} ${statusText[task.status] || ''}`.toLocaleLowerCase('ru').includes(view('tasks').query.toLocaleLowerCase('ru'))); }
  function renderStatusFilters() { return filters.map(([key, label]) => `<button type="button" class="status-chip${view('tasks').status === key ? ' active' : ''}" data-action="status-filter" data-status="${key}" aria-pressed="${view('tasks').status === key}">${label}<span>${state.tasks.filter((task) => statusMatches(task, key)).length}</span></button>`).join(''); }
  function renderTaskItem(task) { return `<button type="button" data-action="open-task" data-id="${esc(task.id)}" data-task-key="${esc(task.id)}" class="task-item${task.id === state.selectedId ? ' active' : ''}" aria-pressed="${task.id === state.selectedId}"><span class="task-item-top">${badge(task.status)}</span><strong>${esc(vacancyTitle(task))}</strong><span class="task-started">${esc(formatDate(task.created_at))}</span></button>`; }
  function renderTasks() {
    return `<div class="task-toolbar"><div class="search-field">${icon('search')}<label class="sr-only" for="task-filter">Поиск заданий</label><input id="task-filter" type="search" placeholder="Поиск заданий" value="${esc(view('tasks').query)}" autocomplete="off"></div></div><div class="status-filters" id="status-filters" aria-label="Фильтр по статусу">${renderStatusFilters()}</div><div class="tasks-workspace" id="tasks-workspace" data-mobile-view="${state.mobileDetail ? 'task' : 'list'}"><section class="panel task-list-panel" aria-label="Список заданий"><div class="panel-heading"><h2>Задания</h2><span class="count-label" id="task-list-count">${filteredTasks().length} из ${state.tasks.length}</span></div><div class="task-list" id="task-list">${filteredTasks().length ? filteredTasks().map(renderTaskItem).join('') : empty('Заданий не найдено', state.tasks.length ? 'Измените поиск или статус' : 'Создайте первое сопоставление')}</div></section><section class="panel task-detail" id="task-detail" tabindex="-1" aria-label="Содержание задания"></section></div>`;
  }

  function patchTaskList() {
    const root = $('#task-list'); if (!root) return;
    const tasks = filteredTasks();
    $('#task-list-count').textContent = `${tasks.length} из ${state.tasks.length}`;
    if (!tasks.length) { setHTML(root, empty('Заданий не найдено', state.tasks.length ? 'Измените поиск или статус' : 'Создайте первое сопоставление')); return; }
    if (!root.querySelector('[data-task-key]')) root.replaceChildren();
    const keys = new Set(tasks.map((task) => task.id));
    $$('[data-task-key]', root).forEach((node) => { if (!keys.has(node.dataset.taskKey)) node.remove(); });
    tasks.forEach((task, index) => {
      const template = document.createElement('template'); template.innerHTML = renderTaskItem(task); const next = template.content.firstElementChild;
      const existing = $$('[data-task-key]', root).find((node) => node.dataset.taskKey === task.id);
      let node = existing;
      if (!existing) node = next;
      else if (existing.outerHTML !== next.outerHTML) { const focused = document.activeElement === existing; existing.replaceWith(next); node = next; if (focused) node.focus({ preventScroll: true }); }
      if (root.children[index] !== node) root.insertBefore(node, root.children[index] || null);
    });
  }

  function patchTasks() {
    if (state.tab !== 'tasks' || !$('#tasks-workspace')) return;
    setHTML($('#status-filters'), renderStatusFilters()); patchTaskList(); patchTaskDetail(); renderHeading(); renderNavigation();
    $('#tasks-workspace').dataset.mobileView = state.mobileDetail ? 'task' : 'list';
  }

  function renderTaskHeader(task) {
    const actions = [];
    if (isRecruiter() && activeStatuses.has(task.status)) actions.push(`<button type="button" class="button" data-action="task-action" data-operation="pause">${icon('pause')}Пауза</button>`);
    if (isRecruiter() && task.status === 'paused') actions.push(`<button type="button" class="button" data-action="task-action" data-operation="resume">${icon('play')}Продолжить</button>`);
    if (canManage() && !['completed', 'destroyed'].includes(task.status)) actions.push(`<button type="button" class="button subtle-danger" data-action="confirm-cancel">${icon('stop')}Остановить</button>`);
    return `<button type="button" class="button mobile-task-back" data-action="task-list">← Все задания</button><div class="detail-title-row"><h2>${esc(vacancyTitle(task))}</h2>${badge(task.status)}</div>${actions.length ? `<div class="task-controls">${actions.join('')}</div>` : ''}`;
  }

  function patchTaskDetail(force = false) {
    const root = $('#task-detail'); if (!root) return;
    const task = state.selectedTask;
    if (!task) { setHTML(root, empty('Выберите задание', isRecruiter() ? 'Откройте задание или создайте сопоставление' : 'Доступные результаты появятся здесь')); return; }
    if (force || root.dataset.taskId !== task.id || !$('#task-panel', root)) {
      root.dataset.taskId = task.id;
      root.innerHTML = '<div class="task-detail-header" id="task-header"></div><div id="task-panel" class="task-panel"></div><div class="detail-bottom" id="task-exports"></div>';
    }
    setHTML($('#task-header'), renderTaskHeader(task));
    const key = JSON.stringify([task.status, task.result, task.approved_ids]), panel = $('#task-panel');
    if (force || panel.dataset.signature !== key) { panel.dataset.signature = key; panel.innerHTML = renderCandidates(task); }
    const csv = task.result && ['recruiter', 'client'].includes(state.user.role);
    $('#task-exports').hidden = !csv;
    setHTML($('#task-exports'), csv ? `<button type="button" class="button" data-action="export">${icon('download')}Скачать CSV</button>` : '');
    syncSelection();
  }

  function renderCandidates(task) {
    const result = task.result;
    if (!result || !Array.isArray(result.candidates)) {
      if (task.status === 'error') return `<div class="notice error" role="alert">${icon('info')}<span>${esc(task.error || 'Обработка завершилась с ошибкой')}</span></div>`;
      if (task.status === 'paused') return empty('Задание на паузе', 'Состояние сохранено. Продолжение доступно в пределах исходного срока', 'pause');
      if (task.status === 'destroyed') return empty('Задание отменено', 'Исполнитель остановлен, история сохранена', 'stop');
      if (task.status === 'waiting') return empty('Ожидает проверки', 'Результат доступен рекрутеру проекта', 'clock');
      if (task.status === 'completed') return empty('Список утвержден', 'Содержимое результата ограничено вашей ролью', 'check');
      return '<div class="processing-state"><span class="spinner" aria-hidden="true"></span><p>Результат появится здесь</p></div>';
    }
    const candidates = arr(result.candidates), approved = new Set(arr(task.approved_ids));
    const warnings = arr(result.warnings).filter((text) => !String(text).startsWith('Балл отражает подтвержденные критерии'));
    return `<div class="result-heading"><div><h3>${task.status === 'completed' && state.user.role === 'client' ? 'Утвержденный список' : 'Кандидаты'} <span class="muted">${candidates.length}</span></h3></div></div>${warnings.length ? `<details class="result-warnings"><summary>Замечания к результату · ${warnings.length}</summary><ul>${warnings.map((text) => `<li>${esc(text)}</li>`).join('')}</ul></details>` : ''}${arr(result.duplicates).length ? `<details class="result-warnings"><summary>Возможные дубли · ${arr(result.duplicates).length}</summary><ul>${arr(result.duplicates).map((item) => `<li>${esc(arr(item.candidate_ids).map((id) => candidates.find((candidate) => candidate.candidate_id === id)?.name || shortId(id)).join(', '))}: ${esc(item.reason)}</li>`).join('')}</ul></details>` : ''}<div class="candidate-list">${candidates.length ? candidates.map((candidate) => renderCandidateCard(candidate, task, approved)).join('') : empty('Кандидаты не найдены', 'Проверьте требования и доступные резюме проекта', 'resumes')}</div>${canApprove(task) && candidates.length ? renderSelectionBar() : ''}`;
  }

  function renderCandidateCard(candidate, task, approved) {
    const selected = state.selectedCandidates.has(candidate.candidate_id), score = Number(candidate.score);
    return `<article class="candidate-card${selected ? ' selected' : ''}" data-candidate-card="${esc(candidate.candidate_id)}">${canApprove(task) ? `<label class="selection-control"><input type="checkbox" data-candidate-id="${esc(candidate.candidate_id)}" aria-label="Включить ${esc(candidate.name)} в список"${selected ? ' checked' : ''}></label>` : ''}<button type="button" class="candidate-open" data-action="open-candidate" data-id="${esc(candidate.candidate_id)}" aria-haspopup="dialog"><span class="candidate-top"><span class="avatar">${esc(initials(candidate.name))}</span><span class="candidate-info"><strong>${esc(candidate.name)}</strong><span>${candidate.experience_years != null ? `Опыт, лет: ${esc(candidate.experience_years)}` : 'Опыт не указан'}${approved.has(candidate.candidate_id) ? ' · В утвержденном списке' : ''}</span></span><span class="candidate-score"><strong>${Number.isFinite(score) ? esc(Number.isInteger(score) ? score : score.toFixed(1)) : '-'}<small>/100</small></strong><span>соответствие</span></span></span><span class="candidate-skills">${arr(candidate.matched_skills).slice(0, 4).map((skill) => `<span class="chip">${esc(skill)}</span>`).join('')}${arr(candidate.matched_skills).length > 4 ? `<span class="chip neutral">+${arr(candidate.matched_skills).length - 4}</span>` : ''}${arr(candidate.missing_skills).length ? `<span class="chip missing">Уточнить: ${arr(candidate.missing_skills).length}</span>` : ''}</span><span class="candidate-link">${icon('arrow')}</span></button></article>`;
  }

  function renderSelectionBar() {
    return `<section class="selection-bar" aria-label="Утверждение списка"><strong id="selection-count">Выбрано: ${state.selectedCandidates.size}</strong><button type="button" id="approve-button" class="button primary" data-action="approve"${state.selectedCandidates.size ? '' : ' disabled'}>Утвердить</button></section>`;
  }

  function syncSelection() {
    $$('[data-candidate-id]').forEach((input) => { input.checked = state.selectedCandidates.has(input.dataset.candidateId); input.disabled = !canApprove(); });
    $$('[data-candidate-card]').forEach((card) => card.classList.toggle('selected', state.selectedCandidates.has(card.dataset.candidateCard)));
    if ($('#selection-count')) $('#selection-count').textContent = `Выбрано: ${state.selectedCandidates.size}`;
    if ($('#approve-button')) $('#approve-button').disabled = !state.selectedCandidates.size || state.busy;
    $$('[data-drawer-selection]').forEach((element) => { element.hidden = !canApprove(); });
  }

  async function openTask(id, { route = true, scroll = true } = {}) {
    saveDraft(); loadController?.abort(); ++loadEpoch; state.loading = false;
    const epoch = ++taskEpoch, token = state.token;
    taskController?.abort(); taskController = new AbortController();
    listScroll = state.mobileDetail ? listScroll : window.scrollY;
    state.selectedId = id; state.mobileDetail = true;
    const cached = state.tasks.find((task) => task.id === id);
    if (cached) setTask(cached); else state.selectedTask = null;
    if (!$('#tasks-workspace')) renderPage(); else patchTasks();
    if (!cached) $('#task-detail').innerHTML = skeleton();
    if (route) writeRoute();
    if (scroll && window.matchMedia('(max-width: 760px)').matches) { $('#task-detail').focus({ preventScroll: true }); window.scrollTo({ top: $('#view-content').offsetTop - 120, behavior: reducedMotion() ? 'auto' : 'smooth' }); }
    try {
      const task = await api(`/api/tasks/${encodeURIComponent(id)}`, { signal: taskController.signal });
      if (token !== state.token || epoch !== taskEpoch || id !== state.selectedId || state.tab !== 'tasks') return;
      setTask(task); patchTasks();
    } catch (error) { if (error.name !== 'AbortError' && state.user && epoch === taskEpoch) { $('#task-detail').innerHTML = `<button class="button mobile-task-back" data-action="task-list">← Все задания</button>${empty('Задание недоступно', error.message, 'info')}`; toast(error.message, true); } }
  }

  async function navigate(tab, id = '', push = true) {
    if (!(roleTabs[state.user?.role] || []).includes(tab)) return;
    saveDraft(); closeDrawer(true); taskController?.abort(); ++taskEpoch;
    state.tab = tab; state.mobileDetail = tab === 'tasks' && !!id;
    if (state.loaded.has(tab)) renderPage(true);
    renderHeading(); renderNavigation();
    if (id) state.selectedId = id;
    writeRoute(push); await loadTab();
    if (id && state.selectedId === id) await openTask(id, { route: false, scroll: false });
  }

  async function taskAction(operation, button) {
    if (state.busy || !state.selectedTask) return;
    loadController?.abort(); pollController?.abort(); ++loadEpoch; ++taskEpoch; state.loading = false;
    state.busy = true; const id = state.selectedId, token = state.token, epoch = taskEpoch;
    if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
    try {
      const body = operation === 'approve' ? { candidate_ids: [...state.selectedCandidates], comment: state.approvalComment.trim() } : undefined;
      const updated = await api(`/api/tasks/${encodeURIComponent(id)}/${operation}`, { method: 'POST', body });
      if (token !== state.token) return;
      if (updated?.id) { const index = state.tasks.findIndex((task) => task.id === updated.id); if (index >= 0) state.tasks[index] = updated; if (state.selectedId === id && taskEpoch === epoch) setTask(updated); }
      if (operation === 'cancel' && $('#entry-dialog').open && $('#dialog-title').textContent === 'Остановить задание?') $('#entry-dialog').close();
      patchTasks();
    } catch (error) { if (token === state.token) toast(error.message, true); }
    finally { if (token === state.token) { state.busy = false; if (button?.isConnected) { button.disabled = false; button.removeAttribute('aria-busy'); } syncSelection(); } }
  }

  async function download(path, filename, button) {
    const token = state.token;
    if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
    try {
      const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
      if (token !== state.token) return;
      if (!response.ok) { if (response.status === 401) logout(false); const data = await response.json().catch(() => ({})); throw new Error(data.detail || 'Не удалось получить файл'); }
      const blob = await response.blob(); if (state.token !== token) return;
      const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (token === state.token) toast(error.message || 'Нет связи с сервером', true); }
    finally { if (token === state.token && button?.isConnected) { button.disabled = false; button.removeAttribute('aria-busy'); } }
  }

  function renderResources() {
    const list = state[state.tab];
    return `<div class="resource-toolbar"><p>${state.tab === 'vacancies' ? 'Вакансий' : 'Резюме'}: ${list.length}</p><div class="search-field">${icon('search')}<label class="sr-only" for="resource-filter">Поиск</label><input id="resource-filter" type="search" placeholder="${state.tab === 'vacancies' ? 'Название вакансии' : 'Имя или email'}" value="${esc(view().query)}"></div></div><div class="resource-grid" id="resource-grid">${renderResourceList()}</div>`;
  }

  function renderResourceList() {
    const vacancies = state.tab === 'vacancies';
    const list = state[state.tab].filter((item) => `${item.title || item.name || ''} ${item.email || ''}`.toLocaleLowerCase('ru').includes(view().query.toLocaleLowerCase('ru')));
    if (!list.length) return `<div class="panel full-span">${empty(view().query ? 'Ничего не найдено' : vacancies ? 'Добавьте вакансию' : 'Добавьте резюме', view().query ? 'Измените запрос' : vacancies ? 'Опишите требования перед сопоставлением' : 'Загрузите PDF или вставьте текст', state.tab)}</div>`;
    return list.map((item) => vacancies ? `<article class="panel resource-card"><h2>${esc(item.title)}</h2><p class="muted">${esc(item.description)}</p><div class="chips">${arr(item.must_have).map((skill) => `<span class="chip">${esc(skill)}</span>`).join('')}${arr(item.nice_to_have).map((skill) => `<span class="chip neutral">${esc(skill)} · желательно</span>`).join('')}</div><div class="resource-footer"><small>Опыт, лет: ${esc(item.min_years || 0)}</small><button type="button" class="button primary" data-action="match-vacancy" data-id="${esc(item.id)}">Найти кандидатов ${icon('arrow')}</button></div></article>` : `<article class="panel resource-card"><div class="resume-top"><span class="avatar">${esc(initials(item.name))}</span><div><h2>${esc(item.name)}</h2><p>${esc(item.email || 'Email не указан')}</p></div>${pdfBadge(item)}</div><div class="resource-footer"><button type="button" class="button" data-action="open-resume" data-id="${esc(item.id)}" aria-haspopup="dialog">Открыть резюме ${icon('arrow')}</button></div></article>`).join('');
  }

  function renderAudit(events) {
    const list = arr(events);
    return `<section class="panel"><div class="panel-heading"><h2>Последние события</h2><span class="count-label">${list.length} из последних 1000 записей</span></div>${list.length ? `<div class="table-wrap" tabindex="0" role="region" aria-label="Таблица аудита, прокручивается по горизонтали"><table class="data-table"><thead><tr><th>Время</th><th>Действие</th><th>Кто</th><th>Проект</th><th>Метаданные</th></tr></thead><tbody>${[...list].reverse().map((event) => `<tr><td>${esc(formatDate(event.at || event.created_at))}</td><td><strong>${esc(eventLabels[event.action] || event.action)}</strong><small>${esc(event.action)}</small></td><td>${esc(auditActor(event))}</td><td>${esc(event.project || '-')}</td><td><details><summary>Открыть</summary><pre>${esc(JSON.stringify(event.detail || {}, null, 2))}</pre></details></td></tr>`).join('')}</tbody></table></div>` : empty('Событий пока нет', 'Здесь появятся действия пользователей и этапы обработки', 'audit')}</section>`;
  }

  function renderAdmin() {
    const labels = { tasks: 'Задания', active: 'Активные исполнители', queue: 'В очереди', workers: 'Вычислительные процессы', states: 'Задания по статусам', api: 'Управляющий API', requests: 'Запросы', errors: 'Ошибки', p95_ms: 'p95 ответа, мс', models: 'Локальные модели', semantic: 'Семантический режим', llm: 'Генератор подсказок', versions: 'Версии', app: 'Приложение', policy: 'Политика', prompt: 'Шаблон запросов', audit: 'Аудит', valid: 'Целостность цепочки', events: 'События', head: 'Последний хэш', ...statusText };
    const pretty = (value) => value === true ? 'Да' : value === false ? 'Нет' : value == null ? '-' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    const entries = Object.entries(state.admin);
    return `<div class="admin-grid">${entries.map(([key, value]) => `<section class="panel admin-card"><h3>${esc(labels[key] || key)}</h3>${typeof value === 'object' && value !== null ? `<dl class="key-values">${Object.entries(value).map(([name, item]) => `<div class="key-value"><dt>${esc(labels[name] || name)}</dt><dd>${esc(pretty(item))}</dd></div>`).join('')}</dl>` : `<strong class="admin-value">${esc(pretty(value))}</strong>`}</section>`).join('')}</div>`;
  }

  function candidateScreen(candidate) {
    const element = document.createElement('section'); element.className = 'drawer-screen';
    const concerns = arr(candidate.concerns), evidence = arr(candidate.evidence), draft = candidate.llm_draft;
    element.innerHTML = `<p class="candidate-drawer-summary">${candidate.experience_years != null ? `Опыт, лет: ${esc(candidate.experience_years)}` : 'Опыт не указан'} · ${esc(candidate.score)} / 100</p><div class="drawer-tabs" role="tablist" aria-label="Карточка кандидата">${[['evidence', 'Подтверждения'], ['questions', 'Вопросы']].map(([key, label], index) => `<button type="button" role="tab" id="drawer-tab-${key}" aria-controls="drawer-panel-${key}" aria-selected="${index === 0}" tabindex="${index === 0 ? '0' : '-1'}" class="${index === 0 ? 'active' : ''}" data-action="drawer-tab" data-tab="${key}">${label}</button>`).join('')}</div><div class="drawer-screen-body" tabindex="-1"><section id="drawer-panel-evidence" data-drawer-panel="evidence" role="tabpanel" aria-labelledby="drawer-tab-evidence">${candidate.summary ? `<p class="drawer-summary">${esc(candidate.summary)}</p>` : ''}${isRecruiter() ? `<button type="button" class="button source-button" data-action="drawer-source" data-id="${esc(candidate.candidate_id)}">Открыть исходное резюме ${icon('arrow')}</button>` : ''}<h3>Цитаты из резюме</h3>${evidence.length ? evidence.map((item) => `<article class="evidence-item"><div><strong>${esc(item.skill === 'experience' ? 'Опыт' : item.skill)}</strong><span class="evidence-status ${['conflicting', 'negated'].includes(item.status) ? item.status : 'stated'}">${esc(evidenceLabels[item.status] || 'Указано в резюме')}</span></div><blockquote>«${esc(item.quote)}»</blockquote></article>`).join('') : '<p class="muted">Цитаты не найдены. Проверьте исходный текст.</p>'}${arr(candidate.missing_skills).length ? `<section class="drawer-section"><h3>Нужно уточнить</h3><div class="chips">${arr(candidate.missing_skills).map((skill) => `<span class="chip missing">${esc(skill)}</span>`).join('')}</div></section>` : ''}${concerns.length ? `<section class="drawer-section"><h3>Замечания</h3><ul class="detail-list">${concerns.map((text) => `<li>${esc(text)}</li>`).join('')}</ul></section>` : ''}</section><section id="drawer-panel-questions" data-drawer-panel="questions" role="tabpanel" aria-labelledby="drawer-tab-questions" hidden><h3>Вопросы к интервью</h3>${arr(candidate.questions).length ? `<ol class="detail-list interview-questions">${candidate.questions.map((question) => `<li>${esc(question)}</li>`).join('')}</ol>` : '<p class="muted">Дополнительных вопросов нет</p>'}${draft ? `<section class="model-draft"><h3>Подсказка локальной модели</h3><p class="muted">Проверьте по источникам</p>${draft.summary ? `<p>${esc(draft.summary)}</p>` : ''}${arr(draft.questions).length ? `<ul class="detail-list">${draft.questions.map((question) => `<li>${esc(question)}</li>`).join('')}</ul>` : ''}</section>` : ''}</section></div><div class="drawer-footer" data-drawer-selection${canApprove() ? '' : ' hidden'}><label class="drawer-select"><input type="checkbox" data-candidate-id="${esc(candidate.candidate_id)}"${state.selectedCandidates.has(candidate.candidate_id) ? ' checked' : ''}><span>Включить в список</span></label></div>`;
    return element;
  }

  function mountDrawer(entry, focus = null) {
    $('#drawer-title').textContent = entry.title;
    $('#drawer-back').hidden = drawer.stack.length < 2;
    $('#drawer-mount').replaceChildren(entry.node);
    const scroller = $('.drawer-screen-body', entry.node); if (scroller) scroller.scrollTop = entry.scroll || 0;
    requestAnimationFrame(() => { if (focus?.isConnected) focus.focus({ preventScroll: true }); else $('#drawer-title').focus({ preventScroll: true }); });
    syncSelection();
  }

  function openDrawer(entry, opener) {
    clearTimeout(drawer.timer); ++drawer.epoch;
    drawer.opener = opener || document.activeElement; drawer.stack = [entry];
    document.body.classList.add('drawer-open');
    const dialog = $('#detail-drawer'); if (!dialog.open) dialog.showModal();
    mountDrawer(entry); requestAnimationFrame(() => dialog.classList.add('is-open'));
  }

  function pushDrawer(entry) {
    const current = drawer.stack.at(-1); if (current) current.scroll = $('.drawer-screen-body', current.node)?.scrollTop || 0;
    entry.returnFocus = document.activeElement; drawer.stack.push(entry); ++drawer.epoch; mountDrawer(entry);
  }

  function drawerBack() {
    if (drawer.stack.length < 2) { closeDrawer(); return; }
    const previous = drawer.stack.pop(); ++drawer.epoch; mountDrawer(drawer.stack.at(-1), previous.returnFocus);
  }

  function closeDrawer(immediate = false) {
    const dialog = $('#detail-drawer'); if (!dialog?.open) return;
    clearTimeout(drawer.timer); ++drawer.epoch; dialog.classList.remove('is-open');
    const finish = () => {
      const opener = drawer.opener; dialog.close(); $('#drawer-mount').replaceChildren(); drawer.stack = []; drawer.opener = null; document.body.classList.remove('drawer-open');
      if (!immediate) { const fallback = $$('[data-action="open-candidate"], [data-action="open-resume"]').find((button) => button.dataset.id === opener?.dataset?.id); (opener?.isConnected ? opener : fallback || $('#task-detail'))?.focus({ preventScroll: true }); }
    };
    if (immediate || reducedMotion()) finish(); else drawer.timer = setTimeout(finish, 180);
  }

  function openCandidate(id, opener) {
    const candidate = arr(state.selectedTask?.result?.candidates).find((item) => item.candidate_id === id); if (!candidate) return;
    openDrawer({ kind: 'candidate', title: candidate.name, taskId: state.selectedId, node: candidateScreen(candidate), scroll: 0 }, opener);
  }

  function sourceScreen(resume) {
    const meta = docMeta(resume), element = document.createElement('section'); element.className = 'drawer-screen';
    element.innerHTML = `<div class="drawer-screen-body resume-document" tabindex="-1">${resume.snapshot ? `<div class="snapshot-note"><strong>Версия сопоставления</strong> · ${esc(formatDate(resume.snapshot.created_at))}</div>` : ''}<div class="source-heading"><p>${esc(resume.email || '')}</p>${pdfBadge(resume)}</div>${meta ? `<div class="document-info"><strong>${esc(meta.filename || 'PDF-документ')}</strong><button type="button" class="button" data-action="download-pdf" data-id="${esc(resume.id)}">${icon('download')}Скачать PDF</button></div>` : ''}<h3>${meta ? 'Извлеченный текст' : 'Текст резюме'}</h3>${meta ? '<p class="muted">Проверьте извлеченный текст</p>' : ''}<div class="resume-text">${esc(resume.text || 'Текст отсутствует')}</div></div>`;
    return element;
  }

  async function openSource(id, nested = false, opener = null, known = null) {
    if (!isRecruiter()) return;
    const placeholder = document.createElement('section'); placeholder.className = 'drawer-screen'; placeholder.innerHTML = skeleton();
    const taskId = nested ? drawer.stack.find((screen) => screen.kind === 'candidate')?.taskId || state.selectedId : '';
    const entry = { kind: 'resume', title: known?.name || 'Исходное резюме', node: placeholder, scroll: 0, id, taskId };
    if (nested) { pushDrawer(entry); if (opener) entry.returnFocus = opener; } else openDrawer(entry, opener);
    const epoch = drawer.epoch, token = state.token;
    try {
      let resume;
      if (taskId) { const source = await api(`/api/tasks/${encodeURIComponent(taskId)}/sources/${encodeURIComponent(id)}`); if (epoch !== drawer.epoch || token !== state.token || drawer.stack.at(-1) !== entry) return; resume = source.resume ? { ...source.resume, snapshot: source.snapshot } : source; }
      else resume = known || state.resumes.find((item) => item.id === id);
      if (!resume) { const resumes = arr(await api('/api/resumes')); if (epoch !== drawer.epoch || token !== state.token || drawer.stack.at(-1) !== entry) return; state.resumes = resumes; state.loaded.add('resumes'); resume = state.resumes.find((item) => item.id === id); }
      if (epoch !== drawer.epoch || token !== state.token || drawer.stack.at(-1) !== entry) return;
      if (!resume) throw new Error('Резюме не найдено или недоступно в вашем проекте');
      entry.title = resume.name; entry.node = sourceScreen(resume); mountDrawer(entry);
    } catch (error) {
      if (epoch !== drawer.epoch || token !== state.token) return;
      entry.node.innerHTML = `<div class="drawer-screen-body region-error" role="alert"><h3>Не удалось открыть резюме</h3><p>${esc(error.message)}</p><button type="button" class="button" data-action="source-retry" data-id="${esc(id)}">Повторить</button></div>`;
    }
  }

  function scopeFields() {
    const items = projects();
    if (items.length === 1) return `<input type="hidden" name="project_id" value="${esc(items[0].id)}">`;
    return `<label>Проект<select name="project_id" required>${items.length ? items.map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('') : '<option value="">Нет доступных проектов</option>'}</select></label>`;
  }

  function showDialog(title, content) {
    $('#dialog-title').textContent = title; $('#dialog-content').innerHTML = content;
    if (!$('#entry-dialog').open) $('#entry-dialog').showModal();
  }

  function createDialog(kind, vacancyId = '') {
    if (!isRecruiter()) return;
    if (kind === 'tasks' && !state.vacancies.length) { toast('Сначала добавьте вакансию', true); navigate('vacancies'); return; }
    let fields;
    if (kind === 'tasks') fields = `<label>Вакансия<select name="vacancy_id" required>${state.vacancies.map((item) => `<option value="${esc(item.id)}"${vacancyId === item.id ? ' selected' : ''}>${esc(item.title)}</option>`).join('')}</select></label>`;
    else if (kind === 'vacancies') fields = `${scopeFields()}<label>Название вакансии<input name="title" required minlength="2" maxlength="200" placeholder="Python-разработчик"></label><label>Описание вакансии<textarea name="description" required minlength="10" maxlength="20000" placeholder="Задачи, контекст и требования"></textarea></label><label>Обязательные навыки<input name="must_have" required maxlength="2000" placeholder="Python, SQL, FastAPI"><span class="field-hint">Через запятую или точку с запятой</span></label><label>Желательные навыки<input name="nice_to_have" maxlength="2000" placeholder="Docker, Kubernetes"></label><div class="form-row"><label>Минимальный опыт, лет<input name="min_years" type="number" min="0" max="60" step="0.5" value="0" required></label><label>Размер списка<input name="top_k" type="number" min="1" max="30" value="5" required></label></div>`;
    else fields = `${scopeFields()}<div class="input-mode" role="tablist" aria-label="Формат резюме"><button type="button" role="tab" aria-selected="true" tabindex="0" class="active" data-action="resume-mode" data-mode="pdf" aria-controls="resume-pdf-panel">PDF</button><button type="button" role="tab" aria-selected="false" tabindex="-1" data-action="resume-mode" data-mode="text" aria-controls="resume-text-panel">Текст</button></div><label>Имя кандидата<input name="name" required minlength="2" maxlength="160" placeholder="Имя и фамилия"></label><label>Email<input name="email" type="email" maxlength="200" placeholder="candidate@example.test"></label><section id="resume-pdf-panel"><label class="dropzone" id="pdf-dropzone" for="resume-file">${icon('upload')}<strong id="pdf-file-name">Выберите PDF или перетащите сюда</strong><span id="pdf-file-meta">PDF с текстом · до 5 МиБ</span><input class="sr-only" id="resume-file" name="file" type="file" accept="application/pdf,.pdf"></label><button type="button" class="button subtle" data-action="remove-pdf" id="remove-pdf" hidden>Убрать файл</button></section><section id="resume-text-panel" hidden><label>Текст резюме<textarea name="text" rows="8" minlength="10" maxlength="30000" placeholder="Опыт, навыки и проекты кандидата" disabled></textarea></label></section>`;
    const labels = { tasks: 'Новое сопоставление', vacancies: 'Новая вакансия', resumes: 'Добавить резюме' };
    showDialog(labels[kind], `<form id="resource-form" data-kind="${kind}" data-mode="pdf" class="form-stack">${fields}<p class="form-error" id="resource-error" role="alert" hidden></p><div class="form-actions"><button type="button" class="button" data-action="close-dialog">Отмена</button><button type="submit" class="button primary">${kind === 'tasks' ? 'Начать сопоставление' : kind === 'vacancies' ? 'Создать вакансию' : 'Загрузить PDF'}</button></div></form>`);
  }

  function validatePdfFile(file) {
    if (!file) return 'Выберите PDF-файл';
    if (file.size > 5 * 1024 * 1024) return 'Файл больше 5 МиБ. Выберите PDF меньшего размера';
    if (!file.name.toLowerCase().endsWith('.pdf') || (file.type && !['application/pdf', 'application/octet-stream'].includes(file.type))) return 'Нужен файл в формате PDF';
    if (!file.size) return 'PDF-файл пуст';
    return '';
  }

  function setPdfFile(form, file) {
    const error = validatePdfFile(file);
    if (error) { pdfFiles.delete(form); $('#resume-file').value = ''; $('#resource-error').textContent = error; $('#resource-error').hidden = false; }
    else { pdfFiles.set(form, file); $('#resource-error').hidden = true; }
    $('#pdf-file-name').textContent = error ? 'Выберите PDF или перетащите сюда' : file.name;
    $('#pdf-file-meta').textContent = error ? 'PDF с текстом · до 5 МиБ' : `${(file.size / 1024).toFixed(0)} КиБ · PDF`;
    $('#remove-pdf').hidden = !!error;
    $('#pdf-dropzone').classList.toggle('has-file', !error);
  }

  function switchResumeMode(mode) {
    const form = $('#resource-form'); if (!form || form.dataset.kind !== 'resumes') return;
    form.dataset.mode = mode;
    $$('[data-action="resume-mode"]', form).forEach((button) => { const selected = button.dataset.mode === mode; button.classList.toggle('active', selected); button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1; });
    $('#resume-pdf-panel').hidden = mode !== 'pdf'; $('#resume-text-panel').hidden = mode !== 'text';
    $('[name="text"]', form).disabled = mode !== 'text'; $('[name="text"]', form).required = mode === 'text';
    $('button[type="submit"]', form).textContent = mode === 'pdf' ? 'Загрузить PDF' : 'Добавить резюме';
    $('#resource-error').hidden = true;
  }

  async function submitResource(form) {
    if (state.busy || !form.reportValidity()) return;
    const token = state.token, values = Object.fromEntries(new FormData(form)), kind = form.dataset.kind, pdf = kind === 'resumes' && form.dataset.mode === 'pdf';
    if (pdf) { const message = validatePdfFile(pdfFiles.get(form)); if (message) { $('#resource-error').textContent = message; $('#resource-error').hidden = false; $('#resume-file').focus(); return; } }
    const split = (value) => String(value || '').split(/[,;\n]+/).map((text) => text.trim()).filter(Boolean);
    let body, path = `/api/${kind}`;
    if (pdf) { body = new FormData(); for (const key of ['name', 'email', 'project_id']) body.append(key, String(values[key] || '').trim()); body.append('file', pdfFiles.get(form)); path = '/api/resumes/pdf'; }
    else if (kind === 'tasks') body = { vacancy_id: values.vacancy_id };
    else if (kind === 'vacancies') body = { tenant_id: state.user.tenant_id, project_id: values.project_id, title: values.title.trim(), description: values.description.trim(), must_have: split(values.must_have), nice_to_have: split(values.nice_to_have), min_years: Number(values.min_years), top_k: Number(values.top_k) };
    else body = { tenant_id: state.user.tenant_id, project_id: values.project_id, name: values.name.trim(), email: values.email.trim(), text: values.text.trim() };
    state.busy = true; const button = $('button[type="submit"]', form); button.disabled = true; button.setAttribute('aria-busy', 'true'); $('#resource-error').hidden = true;
    try {
      if (kind === 'tasks' && form.dataset.requestBody !== JSON.stringify(body)) { form.dataset.requestBody = JSON.stringify(body); form.dataset.requestKey = crypto.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
      const created = await api(path, { method: 'POST', body, headers: kind === 'tasks' ? { 'Idempotency-Key': form.dataset.requestKey } : undefined });
      if (token !== state.token) return;
      $('#entry-dialog').close();
      if (kind === 'tasks') { saveDraft(); state.selectedId = created.id; state.selectedTask = null; state.tab = 'tasks'; state.mobileDetail = true; writeRoute(); }
      await loadTab({ refresh: true });
      if (token !== state.token) return;
      if (pdf) { const resume = created.resume ? { ...created.resume, document: created.document || created.resume.document } : created; if (resume?.id) { const index = state.resumes.findIndex((item) => item.id === resume.id); if (index >= 0) state.resumes[index] = resume; else state.resumes.unshift(resume); openSource(resume.id, false, null, resume); } }
    } catch (error) { if (token === state.token) { if ($('#resource-error')) { $('#resource-error').textContent = error.message; $('#resource-error').hidden = false; } else toast(error.message, true); } }
    finally { if (token === state.token) { state.busy = false; if (button.isConnected) { button.disabled = false; button.removeAttribute('aria-busy'); } } }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      if (!state.user) return;
      if (state.tab !== 'tasks' || state.polling || state.busy || document.hidden || !state.tasks.some((task) => activeStatuses.has(task.status))) { schedulePoll(); return; }
      state.polling = true; const token = state.token, epoch = loadEpoch, selection = taskEpoch;
      pollController = new AbortController();
      try {
        const list = arr(await api('/api/tasks', { signal: pollController.signal }));
        if (token !== state.token || state.tab !== 'tasks' || epoch !== loadEpoch || selection !== taskEpoch) return;
        state.tasks = list;
        if (selection === taskEpoch) { const selected = list.find((task) => task.id === state.selectedId); if (selected) setTask(selected); }
        patchTasks();
      } catch (error) { if (error.name !== 'AbortError' && state.user) toast(error.message, true); }
      finally { state.polling = false; schedulePoll(); }
    }, 2500);
  }

  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return;
    const button = $('button[type="submit"]', form); button.disabled = true; button.setAttribute('aria-busy', 'true'); $('#login-error').hidden = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      const session = await api('/api/login', { method: 'POST', anonymous: true, body: { username: values.username.trim(), password: values.password } });
      state.token = session.token; storage.set(session.token); await enterWorkspace(session.user); $('#password').value = '';
    } catch (error) { $('#login-error').textContent = error.message; $('#login-error').hidden = false; if (!state.user) { state.token = ''; storage.set(''); } }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); }
  });
  $('#demo-users').addEventListener('click', (event) => { const button = event.target.closest('[data-demo]'); if (!button) return; const name = button.dataset.demo; $('#username').value = name; $('#password').value = `${name[0].toUpperCase()}${name.slice(1)}-2026!`; $('#login-form button[type="submit"]').focus(); });
  $('#logout-button').addEventListener('click', () => logout());
  $('#close-dialog').addEventListener('click', () => $('#entry-dialog').close());
  $('#entry-dialog').addEventListener('click', (event) => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.currentTarget.close(); } });
  $('#detail-drawer').addEventListener('cancel', (event) => { event.preventDefault(); drawer.stack.length > 1 ? drawerBack() : closeDrawer(); });
  $('#detail-drawer').addEventListener('click', (event) => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right) closeDrawer(); } });
  document.addEventListener('submit', (event) => { if (event.target.id === 'resource-form') { event.preventDefault(); submitResource(event.target); } });
  document.addEventListener('input', (event) => {
    if (event.target.id === 'task-filter') { view('tasks').query = event.target.value; patchTaskList(); }
    if (event.target.id === 'resource-filter') { view().query = event.target.value; $('#resource-grid').innerHTML = renderResourceList(); }
  });
  document.addEventListener('change', (event) => {
    if (event.target.id === 'resume-file') { if (event.target.files[0]) setPdfFile($('#resource-form'), event.target.files[0]); return; }
    if (!event.target.matches('[data-candidate-id]') || !canApprove()) return;
    const id = event.target.dataset.candidateId; event.target.checked ? state.selectedCandidates.add(id) : state.selectedCandidates.delete(id); saveDraft(); syncSelection();
  });
  document.addEventListener('dragover', (event) => { const zone = event.target.closest('#pdf-dropzone'); if (zone) { event.preventDefault(); zone.classList.add('is-dragging'); } });
  document.addEventListener('dragleave', (event) => { const zone = event.target.closest('#pdf-dropzone'); if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-dragging'); });
  document.addEventListener('drop', (event) => { const zone = event.target.closest('#pdf-dropzone'); if (!zone) return; event.preventDefault(); zone.classList.remove('is-dragging'); if (event.dataTransfer.files.length !== 1) { $('#resource-error').textContent = 'Выберите один PDF-файл'; $('#resource-error').hidden = false; return; } setPdfFile($('#resource-form'), event.dataTransfer.files[0]); });
  document.addEventListener('keydown', (event) => {
    const button = event.target.closest('[role="tab"]'); if (!button || !['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const items = $$('[role="tab"]', button.closest('[role="tablist"]')), index = items.indexOf(button);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    event.preventDefault(); items[next].focus({ preventScroll: true }); items[next].click();
  });
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action]'); if (!button || button.disabled) return;
    const action = button.dataset.action;
    if (action === 'close-toast') $('#toast-region').replaceChildren();
    else if (action === 'close-dialog') $('#entry-dialog').close();
    else if (action === 'tab') await navigate(button.dataset.tab);
    else if (action === 'refresh') await loadTab({ refresh: true });
    else if (action === 'create') createDialog(state.tab);
    else if (action === 'open-task') await openTask(button.dataset.id);
    else if (action === 'task-list') { state.mobileDetail = false; $('#tasks-workspace').dataset.mobileView = 'list'; writeRoute(); requestAnimationFrame(() => { window.scrollTo(0, listScroll); const current = $$('[data-action="open-task"]').find((item) => item.dataset.id === state.selectedId); current?.focus({ preventScroll: true }); }); }
    else if (action === 'status-filter') { view('tasks').status = button.dataset.status; setHTML($('#status-filters'), renderStatusFilters()); patchTaskList(); $$('[data-action="status-filter"]').find((item) => item.dataset.status === view('tasks').status)?.focus({ preventScroll: true }); }
    else if (action === 'open-candidate') openCandidate(button.dataset.id, button);
    else if (action === 'drawer-close') closeDrawer();
    else if (action === 'drawer-back') drawerBack();
    else if (action === 'drawer-tab') { const root = drawer.stack.at(-1)?.node; if (!root) return; $$('[data-action="drawer-tab"]', root).forEach((item) => { const active = item.dataset.tab === button.dataset.tab; item.classList.toggle('active', active); item.setAttribute('aria-selected', String(active)); item.tabIndex = active ? 0 : -1; }); $$('[data-drawer-panel]', root).forEach((panel) => { panel.hidden = panel.dataset.drawerPanel !== button.dataset.tab; }); $('.drawer-screen-body', root).scrollTop = 0; }
    else if (action === 'drawer-source') openSource(button.dataset.id, true);
    else if (action === 'open-resume') openSource(button.dataset.id, false, button);
    else if (action === 'source-retry') { const entry = drawer.stack.pop(); openSource(button.dataset.id, !!drawer.stack.length, entry?.returnFocus); }
    else if (action === 'download-pdf') download(`/api/resumes/${encodeURIComponent(button.dataset.id)}/pdf`, `resume-${shortId(button.dataset.id)}.pdf`, button);
    else if (action === 'match-vacancy') createDialog('tasks', button.dataset.id);
    else if (action === 'task-action') await taskAction(button.dataset.operation, button);
    else if (action === 'export') download(`/api/tasks/${encodeURIComponent(state.selectedId)}/export?format=csv`, 'shortlist.csv', button);
    else if (action === 'approve' && state.selectedCandidates.size) await taskAction('approve', button);
    else if (action === 'confirm-cancel') showDialog('Остановить задание?', `<p class="muted">Отмененное задание нельзя продолжить.</p><div class="form-actions confirm-actions"><button type="button" class="button" data-action="close-dialog">Вернуться</button><button type="button" class="button danger" data-action="cancel-task">Остановить задание</button></div>`);
    else if (action === 'cancel-task') await taskAction('cancel', button);
    else if (action === 'resume-mode') switchResumeMode(button.dataset.mode);
    else if (action === 'remove-pdf') { const form = $('#resource-form'); pdfFiles.delete(form); $('#resume-file').value = ''; $('#pdf-file-name').textContent = 'Выберите PDF или перетащите сюда'; $('#pdf-file-meta').textContent = 'PDF с текстом · до 5 МиБ'; $('#remove-pdf').hidden = true; $('#pdf-dropzone').classList.remove('has-file'); }
  });
  window.addEventListener('popstate', () => { if (!state.user) return; const route = readRoute(); navigate(route.tab || (roleTabs[state.user.role] || [])[0], route.id, false); });
  window.addEventListener('hashchange', () => { if (!state.user) return; const route = readRoute(); if (route.tab !== state.tab || (route.tab === 'tasks' && !!route.id !== state.mobileDetail)) navigate(route.tab, route.id, false); });
  state.token = storage.get();
  if (state.token) {
    const button = $('#login-form button[type="submit"]'); button.disabled = true; button.setAttribute('aria-busy', 'true');
    api('/api/me').then(enterWorkspace).catch((error) => { logout(false); toast(error.message, true); }).finally(() => { button.disabled = false; button.removeAttribute('aria-busy'); });
  }
})();
