import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../frontend/app.js', import.meta.url), 'utf8');
function makeElement(tag = 'div') {
  return {
    tag, className: '', textContent: '', title: '', style: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, removeAttribute() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    addEventListener() {}, scrollIntoView() {},
  };
}

function loadApp() {
  const classList = () => ({ add() {}, remove() {}, toggle() {} });
  const elements = {
    '#sessionType': { value: 'coding' },
    '#sessionTask': { value: 'Draft parser' },
    '#sessionGoal': { value: 'Parse input safely' },
    '#sessionDuration': { value: '25' },
    '#modalStartBtn': { disabled: false },
    '#sessionError': { textContent: '' },
    '#sessions': { scrollIntoView() {} },
    '#recordingConsent': { checked: false, disabled: false },
    '#recordingAppActivityConsent': { checked: false, disabled: false },
    '#companionPairingPanel': { classList: classList() },
    '#companionPairingCode': { value: '' },
    '#companionConnectBtn': { disabled: false },
    '#companionConnectionStatus': { textContent: '' },
    '#recordingPanel': { classList: classList() },
    '#recordingStartBtn': { disabled: false },
    '#recordingStopBtn': { classList: classList() },
    '#recordingDownloadBtn': { classList: classList() },
    '#recordingDiscardBtn': { classList: classList() },
    '#recordingReportDownloadBtn': { classList: classList() },
    '#recordingBundleSaveBtn': { classList: classList() },
    '#recordingReportDeleteBtn': { classList: classList() },
    '#recordingStatus': { textContent: '' },
    '#sessionFloater': { classList: classList() },
    '#floaterRestoreBtn': { classList: classList() },
    '#floaterRestoreTime': { textContent: '' },
    '#floaterNotice': { textContent: '' },
    '#floaterType': { textContent: '' },
    '#floaterTime': { textContent: '' },
    '#floaterState': { textContent: '' },
    '#floaterPauseBtn': { classList: classList() },
    '#floaterResumeBtn': { classList: classList() },
    '#floaterStopBtn': { textContent: '', classList: classList() },
    '#activityPanel': { classList: classList() },
    '#activityReportList': makeElement(),
    '#activityReportsEmpty': { textContent: '', classList: classList() },
    '#activityReportStatus': { textContent: '' },
    '#activityReportsRefreshBtn': { addEventListener() {} },
    '#appTimelineChart': makeElement(),
    '#appTimelineLegend': makeElement(),
    '#liveCurrentApp': { textContent: '', parentElement: { classList: classList() } },
    '#liveCurrentAppBanner': { classList: classList() },
    '#workScorePanel': { classList: classList() },
    '#workScoreRing': { textContent: '', className: '' },
    '#workScoreLabel': { textContent: '' },
    '#workScoreMultiplier': { textContent: '' },
    '#scoreBreakdownBars': makeElement(),
  };
  const context = vm.createContext({
    document: {
      addEventListener() {},
      querySelector(selector) { return elements[selector] || null; },
      getElementById(id) { return elements[`#${id}`] || null; },
      querySelectorAll() { return []; },
      createElement: makeElement,
    },
    window: {},
    performance: { now: () => 1000 },
    URLSearchParams,
    Headers: class {
      constructor(initial = {}) { this.values = { ...initial }; }
      set(name, value) { this.values[name] = value; }
      get(name) { return this.values[name]; }
    },
    fetch: async () => { throw new Error('Unexpected network request in test.'); },
    setInterval: () => 1,
    clearInterval() {},
  });
  vm.runInContext(source, context);
  return { context, elements };
}

test('formats Pydantic validation object arrays as readable field errors', () => {
  const { context } = loadApp();
  const message = context.apiErrorMessage({
    detail: [
      { type: 'missing', loc: ['body', 'session_type'], msg: 'Field required' },
      { type: 'extra_forbidden', loc: ['body', 'type'], msg: 'Extra inputs are not permitted' },
    ],
  }, 422);
  assert.equal(message, 'Session Type: Field required Type: Extra inputs are not permitted');
  assert.equal(message.includes('[object Object]'), false);
});

test('keeps backend string errors intact and supplies a status fallback', () => {
  const { context } = loadApp();
  assert.equal(context.apiErrorMessage({ detail: 'A session is already active' }, 409), 'A session is already active');
  assert.equal(context.apiErrorMessage({}, 503), 'The request could not be completed (HTTP 503).');
});

test('session form maps every session kind to the backend field and activates only on success', async () => {
  for (const type of ['coding', 'learning', 'research', 'assignment', 'creative', 'video', 'break']) {
    const { context, elements } = loadApp();
    elements['#sessionType'].value = type;
    let sent;
    let closed = false;
    let rendered = null;
    context.api = async (path, options) => {
      sent = { path, payload: JSON.parse(options.body) };
      return { id: 'session-id', type, status: 'running', elapsed_seconds: 0 };
    };
    context.closeModal = () => { closed = true; };
    context.renderSession = session => { rendered = session; };

    await context.startSession();

    assert.equal(sent.path, '/api/sessions');
    assert.equal(sent.payload.session_type, type);
    assert.equal('type' in sent.payload, false);
    assert.equal(closed, true);
    assert.equal(rendered.type, type);
    assert.equal(elements['#modalStartBtn'].disabled, false);
  }
});

test('session failures keep modal input and form state without rendering an active timer', async () => {
  const { context, elements } = loadApp();
  let closed = false;
  let rendered = false;
  context.api = async () => { throw new Error('Session type: Field required'); };
  context.closeModal = () => { closed = true; };
  context.renderSession = () => { rendered = true; };

  await context.startSession();

  assert.equal(closed, false);
  assert.equal(rendered, false);
  assert.equal(elements['#sessionTask'].value, 'Draft parser');
  assert.equal(elements['#sessionGoal'].value, 'Parse input safely');
  assert.equal(elements['#sessionError'].textContent, 'Session type: Field required');
  assert.equal(elements['#modalStartBtn'].disabled, false);
});

test('duplicate start clicks issue only one request while the first is pending', async () => {
  const { context } = loadApp();
  let calls = 0;
  let resolveRequest;
  context.api = () => {
    calls += 1;
    return new Promise(resolve => { resolveRequest = resolve; });
  };
  context.closeModal = () => {};
  context.renderSession = () => {};

  const first = context.startSession();
  const second = context.startSession();
  assert.equal(calls, 1);
  resolveRequest({ id: 'one', type: 'coding', status: 'running', elapsed_seconds: 0 });
  await Promise.all([first, second]);
  assert.equal(calls, 1);
});

test('screen capture requires consent and is disabled in Private Mode', async () => {
  const { context, elements } = loadApp();
  let requests = 0;
  context.navigator = { mediaDevices: { getDisplayMedia: async () => { requests += 1; } } };
  vm.runInContext("currentSession = { id: 'private-1', type: 'private', status: 'running' }", context);
  await context.startScreenRecording();
  assert.equal(requests, 0);

  vm.runInContext("currentSession = { id: 'coding-1', type: 'coding', status: 'running' }", context);
  await context.startScreenRecording();
  assert.equal(requests, 0);
  assert.match(elements['#recordingStatus'].textContent, /consent box/i);
});

test('unsupported browsers get a clear disabled-recording state', async () => {
  const { context, elements } = loadApp();
  elements['#recordingConsent'].checked = true;
  context.navigator = {};
  vm.runInContext("currentSession = { id: 'coding-1', type: 'coding', status: 'running' }", context);
  context.updateRecordingUI();
  assert.equal(elements['#recordingStartBtn'].disabled, true);
  assert.match(elements['#recordingStatus'].textContent, /not supported/i);
});

test('denied screen-share permission reports a clear error and leaves timer state alone', async () => {
  const { context, elements } = loadApp();
  elements['#recordingConsent'].checked = true;
  context.navigator = {
    mediaDevices: {
      getDisplayMedia: async () => { throw Object.assign(new Error('cancelled'), { name: 'NotAllowedError' }); },
    },
  };
  context.MediaRecorder = class {
    static isTypeSupported() { return false; }
  };
  vm.runInContext("currentSession = { id: 'coding-1', type: 'coding', status: 'paused' }", context);

  await context.startScreenRecording();

  assert.match(elements['#recordingStatus'].textContent, /denied or cancelled/i);
  assert.match(elements['#recordingStatus'].textContent, /Timer state is unchanged/);
  assert.equal(vm.runInContext('currentSession.status', context), 'paused');
});

test('screen-share end stops tracks and saves the in-memory recording only after an explicit download click', async () => {
  const { context, elements } = loadApp();
  const trackHandlers = {};
  const track = {
    stopped: false,
    addEventListener(name, callback) { trackHandlers[name] = callback; },
    stop() { this.stopped = true; },
  };
  const stream = { getVideoTracks: () => [track], getTracks: () => [track] };
  const recorderEvents = {};
  let downloadClicks = 0;
  let objectUrls = 0;
  const link = { click() { downloadClicks += 1; }, remove() {} };
  class MockRecorder {
    static isTypeSupported() { return true; }
    constructor(_stream, options) { this.mimeType = options.mimeType; this.state = 'inactive'; }
    addEventListener(name, callback) { recorderEvents[name] = callback; }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      recorderEvents.dataavailable({ data: { size: 1 } });
      recorderEvents.stop();
    }
  }
  elements['#recordingConsent'].checked = true;
  context.MediaRecorder = MockRecorder;
  context.navigator = { mediaDevices: { getDisplayMedia: async () => stream } };
  context.Blob = class { constructor(chunks, options) { this.size = chunks.length; this.type = options.type; } };
  context.URL = { createObjectURL() { objectUrls += 1; return 'blob:local-recording'; }, revokeObjectURL() {} };
  context.window.setTimeout = callback => callback();
  context.document.body = { append() {} };
  context.document.createElement = () => link;
  vm.runInContext("currentSession = { id: 'coding-1', type: 'coding', status: 'running' }", context);

  await context.startScreenRecording();
  assert.equal(vm.runInContext('recordingState', context), 'recording');
  trackHandlers.ended();

  assert.equal(vm.runInContext('recordingState', context), 'ready');
  assert.equal(track.stopped, true);
  assert.match(elements['#recordingStatus'].textContent, /Download it or discard it/);
  assert.equal(downloadClicks, 0);
  assert.equal(objectUrls, 0);

  context.downloadRecording();

  assert.equal(downloadClicks, 1);
  assert.equal(objectUrls, 1);
  assert.equal(vm.runInContext('completedRecording', context), null);
  assert.equal(vm.runInContext('recordingState', context), 'idle');
});

test('recording startup failures stop acquired tracks and keep the timer usable', async () => {
  const { context, elements } = loadApp();
  const track = { stopped: false, addEventListener() {}, stop() { this.stopped = true; } };
  const stream = { getVideoTracks: () => [track], getTracks: () => [track] };
  class BrokenRecorder {
    static isTypeSupported() { return false; }
    constructor() { this.state = 'inactive'; }
    addEventListener() {}
    start() { throw new Error('recorder initialization failed'); }
  }
  elements['#recordingConsent'].checked = true;
  context.MediaRecorder = BrokenRecorder;
  context.navigator = { mediaDevices: { getDisplayMedia: async () => stream } };
  vm.runInContext("currentSession = { id: 'coding-1', type: 'coding', status: 'running' }", context);

  await context.startScreenRecording();

  assert.equal(track.stopped, true);
  assert.equal(vm.runInContext('recordingState', context), 'error');
  assert.match(elements['#recordingStatus'].textContent, /recorder initialization failed/);
  assert.equal(vm.runInContext('currentSession.status', context), 'running');
});

test('companion pairing keeps the code in the tab and checks the local service', async () => {
  const { context, elements } = loadApp();
  context.navigator = {};
  const stored = {};
  context.window.sessionStorage = {
    setItem(name, value) { stored[name] = value; },
    removeItem(name) { delete stored[name]; },
  };
  const requests = [];
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => (url.endsWith('/api/recordings') ? { recordings: [] } : { ready: true, tracking: false }),
    };
  };

  assert.equal(await context.connectCompanion('local-pair-code'), true);
  assert.equal(requests[0].url, 'http://127.0.0.1:8765/api/status');
  assert.equal(requests[0].options.headers.get('Authorization'), 'Bearer local-pair-code');
  assert.ok(requests.some(request => request.url.endsWith('/api/recordings')));
  assert.equal(stored.focusforge_companion_code, 'local-pair-code');
  assert.match(elements['#companionConnectionStatus'].textContent, /Connected/);
});

test('screen video and app report use one recording ID and stop tracking together', async () => {
  const { context, elements } = loadApp();
  const recordingId = 'f5a0f95a-b67e-4be2-9201-5a06f3d1a954';
  const requests = [];
  const trackHandlers = {};
  const track = {
    addEventListener(name, callback) { trackHandlers[name] = callback; },
    stop() {},
  };
  const stream = { getVideoTracks: () => [track], getTracks: () => [track] };
  const recorderEvents = {};
  const downloads = [];
  class MockRecorder {
    static isTypeSupported() { return true; }
    constructor(_stream, options) { this.mimeType = options.mimeType; this.state = 'inactive'; }
    addEventListener(name, callback) { recorderEvents[name] = callback; }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      recorderEvents.dataavailable({ data: { size: 1 } });
      recorderEvents.stop();
    }
  }
  context.window.crypto = { randomUUID: () => recordingId };
  context.window.setTimeout = callback => callback();
  context.document.body = { append() {} };
  context.document.createElement = () => ({
    click() { downloads.push(this.download); }, remove() {},
  });
  context.URL = { createObjectURL: () => 'blob:local', revokeObjectURL() {} };
  context.Blob = class { constructor(chunks) { this.size = chunks.length; } };
  context.navigator = { mediaDevices: { getDisplayMedia: async () => stream } };
  context.MediaRecorder = MockRecorder;
  vm.runInContext("companionPairingCode = 'paired-code'; companionConnected = true", context);
  elements['#recordingConsent'].checked = true;
  elements['#recordingAppActivityConsent'].checked = true;
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        recording_id: recordingId,
        status: url.endsWith(`/api/recordings/${recordingId}/stop`) ? 'completed' : 'recording',
      }),
      blob: async () => new Uint8Array([1, 2]),
    };
  };
  vm.runInContext("currentSession = { id: 'web-session', type: 'coding', status: 'running' }", context);

  await context.startScreenRecording();
  assert.equal(vm.runInContext('recordingState', context), 'recording');
  assert.match(elements['#recordingStatus'].textContent, /local app timeline are active/i);
  assert.equal(JSON.parse(requests[0].options.body).recording_id, recordingId);
  assert.equal(JSON.parse(requests[0].options.body).session_type, 'coding');
  trackHandlers.ended();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(vm.runInContext('recordingState', context), 'ready');
  assert.equal(vm.runInContext('appActivityReportId', context), recordingId);
  assert.match(elements['#recordingStatus'].textContent, /app activity Excel is ready/i);
  assert.ok(requests.some(request => request.url.endsWith(`/api/recordings/${recordingId}/stop`)));

  context.downloadRecording();
  await context.downloadAppActivityReport();
  assert.deepEqual(downloads, [`focusforge-${recordingId}.webm`, `focusforge-${recordingId}-app-activity.xlsx`]);
});

test('saved app activity reports list and open per-app usage time', async () => {
  const { context, elements } = loadApp();
  const recordingId = 'f5a0f95a-b67e-4be2-9201-5a06f3d1a954';
  vm.runInContext("companionPairingCode = 'paired-code'; companionConnected = true", context);
  const requests = [];
  context.fetch = async url => {
    requests.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        recordings: [{
          id: recordingId, session_type: 'coding', status: 'completed',
          started_at: '2026-10-24T10:30:00+05:30', ended_at: '2026-10-24T10:35:00+05:30',
          foreground_seconds: 300,
        }],
      }),
    };
  };

  await context.loadActivityReports({ reveal: true });

  assert.deepEqual(requests, ['http://127.0.0.1:8765/api/recordings']);
  assert.equal(elements['#activityReportList'].children.length, 1);
  const row = elements['#activityReportList'].children[0];
  assert.equal(row.children[0].textContent, '2026-10-24 10:30');
  assert.equal(row.children[1].textContent, 'coding · completed · 5m of app time');
  assert.equal(row.children[2].textContent, 'View app time');
  assert.equal(row.children[3].textContent, 'Excel');
  assert.match(elements['#activityReportStatus'].textContent, /1 saved report on this device/);

  let requested = '';
  context.api = async path => {
    requested = path;
    return {
      score: 90, label: 'Deep Work', coin_multiplier: 1.5,
      productive_seconds: 240, distraction_seconds: 60, neutral_seconds: 0,
      total_seconds: 300,
      apps: [
        { app_name: 'code.exe', elapsed_seconds: 240, minutes: 4, percent: 80, category: 'productive', weight: 1 },
        { app_name: 'chrome.exe', elapsed_seconds: 60, minutes: 1, percent: 20, category: 'productive', weight: 0.5 },
      ],
    };
  };

  await context.openActivityReport({ id: recordingId, session_type: 'coding' });

  assert.match(requested, new RegExp(`^/api/activity/reports/${recordingId}\\?`));
  assert.match(requested, /session_type=coding/);
  assert.match(requested, /companion_token=paired-code/);
  const legend = elements['#appTimelineLegend'].children;
  assert.equal(legend.length, 2);
  assert.equal(legend[0].children[1].textContent, 'code.exe — 4m (80%)');
  assert.equal(legend[1].children[1].textContent, 'chrome.exe — 1m (20%)');
  assert.match(elements['#activityReportStatus'].textContent, /5m of app time across 2 app/);
  assert.equal(elements['#workScoreRing'].textContent, '90');
});

test('the combined save writes video and workbook into one user-selected folder', async () => {
  const { context, elements } = loadApp();
  const recordingId = 'f5a0f95a-b67e-4be2-9201-5a06f3d1a954';
  const saved = {};
  context.window.showDirectoryPicker = async () => ({
    async getFileHandle(name) {
      return {
        async createWritable() {
          return {
            async write(blob) { saved[name] = blob; },
            async close() {},
          };
        },
      };
    },
  });
  context.fetch = async () => ({ ok: true, status: 200, blob: async () => ({ kind: 'excel', size: 128 }) });
  context.Blob = class { constructor(chunks, options) { this.chunks = chunks; this.type = options.type; this.size = chunks.length ? 1 : 0; } };
  context.navigator = { mediaDevices: { getDisplayMedia: async () => {} } };
  vm.runInContext(`
    currentSession = { id: 'web-session', type: 'coding', status: 'running' };
    companionPairingCode = 'paired-code';
    completedRecording = { recordingId: '${recordingId}', chunks: [{ size: 1 }], mimeType: 'video/webm' };
    appActivityReportId = '${recordingId}';
  `, context);

  await context.saveRecordingBundle();

  assert.deepEqual(Object.keys(saved), [
    `focusforge-${recordingId}.webm`,
    `focusforge-${recordingId}-app-activity.xlsx`,
  ]);
  assert.equal(elements['#recordingStatus'].textContent, 'Video and matching app activity Excel were saved together in the selected folder.');
  assert.equal(vm.runInContext('completedRecording', context), null);
});
