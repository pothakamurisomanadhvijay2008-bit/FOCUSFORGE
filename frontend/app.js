'use strict';

const $ = (selector, context = document) => context.querySelector(selector);
const $$ = (selector, context = document) => [...context.querySelectorAll(selector)];

const SESSION_TYPES = {
  coding: {
    label: 'Coding', icon: '⌨️', hint: 'Build, debug, or review code.',
    task: 'What are you building or debugging?', goal: 'Code outcome', completion: 'What code did you complete?',
  },
  learning: {
    label: 'Learning', icon: '📚', hint: 'Study a topic or practice a new concept.',
    task: 'What topic or concept are you studying?', goal: 'Learning outcome', completion: 'What did you learn or practice?',
  },
  research: {
    label: 'Research', icon: '🔎', hint: 'Investigate a question and record useful findings.',
    task: 'What question are you researching?', goal: 'Finding to capture', completion: 'What finding did you capture?',
  },
  assignment: {
    label: 'Assignment', icon: '📝', hint: 'Work through a defined assignment or deliverable.',
    task: 'What assignment are you working on?', goal: 'Deliverable', completion: 'What part of the assignment did you finish?',
  },
  creative: {
    label: 'Creative work', icon: '🎨', hint: 'Draft, design, compose, or make something.',
    task: 'What are you creating?', goal: 'Creative outcome', completion: 'What did you make or change?',
  },
  video: {
    label: 'Learning video', icon: '▶️', hint: 'Watch a lesson or tutorial you chose for this study session.',
    task: 'What lesson or topic are you watching?', goal: 'Learning outcome', completion: 'What did you learn from the video?',
  },
  private: {
    label: 'Private work', icon: '🔒', hint: 'This timer stays in this tab and is never saved.',
    task: 'Private task description (kept only in this tab)', goal: 'Private outcome', completion: 'Private completion note',
  },
  break: {
    label: 'Break', icon: '☕', hint: 'Track a break separately from focus time.',
    task: 'Optional note about this break', goal: 'Optional intention', completion: 'How was your break?',
  },
};
const COMPANION_ORIGIN = 'http://127.0.0.1:8765';

let currentUser = null;
let currentSession = null;
let timerTick = null;
let checkpointTick = null;
let timerAnchor = 0;
let elapsedAtAnchor = 0;
let requestBusy = false;
let activeRecorder = null;
let completedRecording = null;
let recordingState = 'idle';
let companionPairingCode = '';
let companionConnected = false;
let companionTrackingId = '';
let companionHeartbeatTick = null;
let appActivityReportId = '';
let appReportMessage = '';
let floaterHidden = false;
let pictureInPictureWindow = null;
let analyticsPeriod = 'weekly';
let analyticsAnchor = localDateString();
let coinRatesPer15Minutes = {};
let appRules = {};
let activityReports = [];

function floaterElement(id) {
  return pictureInPictureWindow?.document.getElementById(id) || document.getElementById(id);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Please sign in again.');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiErrorMessage(data, response.status));
  return data;
}

async function companionFetch(path, options = {}) {
  if (!companionPairingCode) throw new Error('Enter the pairing code shown in the Windows companion first.');
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${companionPairingCode}`);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  let response;
  try {
    const timeoutSignal = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(5000) : undefined;
    response = await fetch(`${COMPANION_ORIGIN}${path}`, {
      ...options,
      headers,
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      signal: timeoutSignal,
    });
  } catch (error) {
    if (error?.name === 'TimeoutError' || error?.name === 'AbortError') {
      throw new Error('The Windows companion did not respond. Leave it open and try again.');
    }
    throw new Error('Could not reach the Windows companion. Start it and pair this browser tab again.');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(apiErrorMessage(data, response.status));
  }
  return response;
}

async function connectCompanion(pairingCode = $('#companionPairingCode').value.trim(), quiet = false) {
  if (!pairingCode) {
    $('#companionConnectionStatus').textContent = 'Paste the pairing code shown in the open Windows companion.';
    return false;
  }
  companionPairingCode = pairingCode;
  companionConnected = false;
  try {
    const response = await companionFetch('/api/status');
    const status = await response.json();
    if (!status.ready) throw new Error('The Windows companion is not ready.');
    companionPairingCode = pairingCode;
    companionConnected = true;
    if (window.sessionStorage) window.sessionStorage.setItem('focusforge_companion_code', pairingCode);
    $('#companionPairingCode').value = pairingCode;
    $('#companionConnectionStatus').textContent = status.tracking
      ? `Connected · app tracking is already active for ${status.session_type}.`
      : 'Connected · app names and timing will stay on this device.';
    updateRecordingUI();
    void loadActivityReports({ reveal: true, silent: true });
    return true;
  } catch (error) {
    companionPairingCode = '';
    companionConnected = false;
    window.sessionStorage?.removeItem('focusforge_companion_code');
    $('#companionConnectionStatus').textContent = quiet
      ? 'The saved pairing code did not reconnect. Check that the companion is open and connect again.'
      : errorMessage(error, 'Could not connect to the companion.');
    updateRecordingUI();
    return false;
  }
}

function apiErrorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(issue => {
      if (typeof issue === 'string') return issue;
      if (!issue || typeof issue !== 'object') return '';
      const fieldPath = Array.isArray(issue.loc)
        ? issue.loc.filter(part => !['body', 'query', 'path'].includes(String(part))).join(' ')
        : '';
      const field = fieldPath.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
      const message = typeof issue.msg === 'string' ? issue.msg.replace(/^Value error, /, '') : '';
      return [field, message].filter(Boolean).join(': ');
    }).filter(Boolean);
    if (messages.length) return messages.join(' ');
  }
  if (detail && typeof detail === 'object') {
    for (const key of ['message', 'error']) {
      if (typeof detail[key] === 'string' && detail[key].trim()) return detail[key];
    }
  }
  for (const key of ['message', 'error']) {
    if (typeof data?.[key] === 'string' && data[key].trim()) return data[key];
  }
  return `The request could not be completed (HTTP ${status}).`;
}

function errorMessage(error, fallback = 'The request could not be completed. Check your connection and try again.') {
  if (typeof error === 'string' && error.trim()) return error;
  if (error && typeof error === 'object' && typeof error.message === 'string' && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

function setError(message) {
  const el = $('#sessionError');
  const safeMessage = typeof message === 'string' ? message : 'The request could not be completed.';
  if (el) el.textContent = safeMessage;
  const floaterNotice = floaterElement('floaterNotice');
  if (floaterNotice && currentSession) floaterNotice.textContent = safeMessage;
}

function formatTime(seconds) {
  const safe = Math.max(0, Math.floor(seconds));
  const h = String(Math.floor(safe / 3600)).padStart(2, '0');
  const m = String(Math.floor((safe % 3600) / 60)).padStart(2, '0');
  const s = String(safe % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function currentElapsed() {
  if (!currentSession) return 0;
  if (currentSession.status !== 'running') return elapsedAtAnchor;
  return elapsedAtAnchor + (performance.now() - timerAnchor) / 1000;
}

function updateTimerDisplay() {
  const display = $('#timerDisplay');
  if (display) display.textContent = formatTime(currentElapsed());
  const floaterTime = floaterElement('floaterTime');
  if (floaterTime) floaterTime.textContent = formatTime(currentElapsed());
  const restoreTime = $('#floaterRestoreTime');
  if (restoreTime && currentSession) restoreTime.textContent = formatTime(currentElapsed());
}

function stopClock() {
  clearInterval(timerTick);
  clearInterval(checkpointTick);
  timerTick = null;
  checkpointTick = null;
}

function updateFloatingIndicator() {
  const floater = floaterElement('sessionFloater');
  if (!floater) return;
  const restore = $('#floaterRestoreBtn');
  if (!currentSession) {
    floater.classList.add('hidden');
    restore.classList.add('hidden');
    if (pictureInPictureWindow) pictureInPictureWindow.close();
    return;
  }
  if (floaterHidden) {
    floater.classList.add('hidden');
    restore.classList.remove('hidden');
    $('#floaterRestoreTime').textContent = formatTime(currentElapsed());
    return;
  }
  restore.classList.add('hidden');
  const meta = SESSION_TYPES[currentSession.type] || SESSION_TYPES.coding;
  const state = currentSession.status === 'running' ? 'running'
    : currentSession.status === 'paused' ? 'paused'
      : currentSession.status === 'interrupted' ? 'interrupted' : currentSession.status;
  floaterElement('floaterType').textContent = `${meta.icon} ${meta.label}`;
  floaterElement('floaterTime').textContent = formatTime(currentElapsed());
  const screenState = recordingState === 'recording' ? 'recording'
    : recordingState === 'requesting' ? 'permission requested'
      : recordingState === 'stopping' ? 'stopping'
        : recordingState === 'ready' ? 'ready to download'
        : 'not recording';
  floaterElement('floaterState').textContent = `Timer: ${state} · Screen: ${screenState}`;
  floaterElement('floaterPauseBtn').classList.toggle('hidden', state !== 'running');
  floaterElement('floaterResumeBtn').classList.toggle('hidden', state !== 'paused');
  floaterElement('floaterStopBtn').textContent = state === 'interrupted' ? 'Close' : 'Stop';
  floater.classList.remove('hidden');
}

function updateRecordingUI(message = '') {
  const panel = $('#recordingPanel');
  if (!panel) return;
  const privateMode = currentSession?.type === 'private';
  const canRecord = Boolean(currentSession && ['running', 'paused'].includes(currentSession.status));
  panel.classList.toggle('hidden', privateMode || !canRecord);
  const consent = $('#recordingConsent');
  const appConsent = $('#recordingAppActivityConsent');
  const pairingPanel = $('#companionPairingPanel');
  const start = $('#recordingStartBtn');
  const stop = $('#recordingStopBtn');
  const download = $('#recordingDownloadBtn');
  const discard = $('#recordingDiscardBtn');
  const reportDownload = $('#recordingReportDownloadBtn');
  const bundleSave = $('#recordingBundleSaveBtn');
  const reportDelete = $('#recordingReportDeleteBtn');
  const connect = $('#companionConnectBtn');
  const status = $('#recordingStatus');
  const isRecording = recordingState === 'recording' || recordingState === 'requesting' || recordingState === 'stopping';
  const recordingSupported = Boolean(navigator.mediaDevices?.getDisplayMedia && typeof MediaRecorder !== 'undefined');
  const appTrackingRequired = appConsent.checked;
  pairingPanel.classList.toggle('hidden', !appTrackingRequired);
  start.disabled = privateMode || !canRecord || !recordingSupported || !consent.checked || isRecording
    || Boolean(completedRecording) || Boolean(appActivityReportId) || (appTrackingRequired && !companionConnected);
  stop.classList.toggle('hidden', recordingState !== 'recording');
  download.classList.toggle('hidden', !completedRecording);
  discard.classList.toggle('hidden', !completedRecording);
  reportDownload.classList.toggle('hidden', !appActivityReportId);
  bundleSave.classList.toggle('hidden', !(completedRecording && appActivityReportId));
  reportDelete.classList.toggle('hidden', !appActivityReportId);
  connect.disabled = isRecording;
  consent.disabled = isRecording || Boolean(completedRecording) || privateMode;
  appConsent.disabled = isRecording || Boolean(completedRecording) || privateMode || Boolean(appActivityReportId);
  if (message) status.textContent = message;
  else if (appReportMessage) status.textContent = appReportMessage;
  else if (recordingState === 'recording') status.textContent = companionTrackingId
    ? 'Screen recording and the local app timeline are active. The companion is sampling foreground app names and time; stop to prepare the separate app activity Excel.'
    : 'Screen recording is active. Timer state is shown separately. Captured data stays in this tab until you download or discard it.';
  else if (recordingState === 'requesting') status.textContent = 'Waiting for screen-share permission. Timer state is shown separately.';
  else if (recordingState === 'stopping') status.textContent = 'Stopping the screen recording…';
  else if (appActivityReportId) status.textContent = completedRecording
    ? `A matching app activity report is ready. Use “Save video + Excel together” to choose one folder; both files share recording ID ${appActivityReportId}.`
    : `The matching app activity Excel is ready for recording ${appActivityReportId}.`;
  else if (completedRecording) status.textContent = 'Screen recording stopped. Download it or discard it; it has not been uploaded.';
  else if (recordingState === 'error') status.textContent = 'Screen recording could not start. The timer is unchanged. You can try again.';
  else if (canRecord && !recordingSupported) status.textContent = 'Screen recording is not supported by this browser or connection. Your timer works independently.';
  else status.textContent = appTrackingRequired
    ? (companionConnected
      ? 'Companion connected. Starting a recording will also capture foreground executable names and timing locally.'
      : 'Open the Windows companion, copy its pairing code, and connect it here before recording.')
    : 'Timer activity and screen recording have separate controls. Recording is optional and stays in this tab.';
  updateFloatingIndicator();
}

function showIdle() {
  const wasPrivate = currentSession?.type === 'private';
  stopClock();
  currentSession = null;
  elapsedAtAnchor = 0;
  $('#completionNote').value = '';
  $('#focusRating').value = '';
  $('#distractionCount').textContent = '0';
  if (wasPrivate) {
    $('#sessionTask').value = '';
    $('#sessionGoal').value = '';
  }
  $('#sessionIdle').classList.remove('hidden');
  $('#sessionActive').classList.add('hidden');
  $('#timerDisplay').textContent = '00:00:00';
  $('#sessionState').textContent = 'Timer: stopped';
  $('#startSessionBtn').disabled = false;
  $('#startSessionBtn2').disabled = false;
  updateFloatingIndicator();
}

function renderSession(session) {
  const sessionChanged = currentSession?.id !== session.id;
  stopClock();
  currentSession = session;
  elapsedAtAnchor = Number(session.elapsed_seconds || 0);
  timerAnchor = performance.now();
  if (sessionChanged) $('#recordingConsent').checked = false;
  const meta = SESSION_TYPES[session.type] || SESSION_TYPES.coding;
  $('#sessionIdle').classList.add('hidden');
  $('#sessionActive').classList.remove('hidden');
  $('#sessionTag').textContent = `${meta.icon} ${meta.label}`;
  $('#activeTask').textContent = session.task_description || meta.hint;
  $('#activeGoal').textContent = session.goal ? `${meta.goal}: ${session.goal}` : '';
  $('#completionLabel').textContent = `${meta.completion} (optional)`;
  if (sessionChanged && session.completion_note) $('#completionNote').value = session.completion_note;
  $('#timerDisplay').textContent = formatTime(elapsedAtAnchor);
  if (sessionChanged) $('#focusRating').value = session.focus_rating ? String(session.focus_rating) : '';
  else if (session.focus_rating) $('#focusRating').value = String(session.focus_rating);
  $('#distractionCount').textContent = String(Number(session.distraction_count || 0));
  $('#sessionSelfReport').classList.toggle('hidden', session.type === 'break');

  const interrupted = session.status === 'interrupted';
  const privateMode = session.type === 'private';
  $('#sessionNotice').textContent = interrupted
    ? 'The server restarted. Only time saved at the last checkpoint is shown; no offline time was added.'
    : privateMode
      ? 'Private timer: this tab only. No session details are sent, saved, recorded, or monitored.'
      : 'Manual timer only. Idle time and desktop app activity are not monitored.';
  $('#pauseBtn').classList.toggle('hidden', session.status !== 'running');
  $('#resumeBtn').classList.toggle('hidden', session.status !== 'paused');
  $('#stopBtn').textContent = interrupted ? 'Close interrupted session' : '⏹ End Session';
  $('#stopBtn').disabled = false;
  $('#startSessionBtn').disabled = session.status === 'running' || session.status === 'paused';
  $('#startSessionBtn2').disabled = session.status === 'running' || session.status === 'paused';
  const timerState = session.status === 'running' ? 'running'
    : session.status === 'paused' ? 'paused'
      : session.status === 'interrupted' ? 'interrupted at last checkpoint' : session.status;
  $('#sessionState').textContent = `Timer: ${timerState}`;
  updateRecordingUI();
  updateFloatingIndicator();

  if (session.status === 'running') {
    timerTick = setInterval(updateTimerDisplay, 1000);
    if (!privateMode) checkpointTick = setInterval(checkpointSession, 15000);
  }
}

async function checkpointSession() {
  if (!currentSession || currentSession.type === 'private' || currentSession.status !== 'running' || requestBusy) return;
  try {
    const updated = await api(`/api/sessions/${encodeURIComponent(currentSession.id)}/checkpoint`, { method: 'POST' });
    if (currentSession?.id === updated.id && currentSession.status === 'running') renderSession(updated);
  } catch (error) {
    setError(`Timer checkpoint failed: ${errorMessage(error)}`);
  }
}

function updateDate() {
  $('#pageDate').textContent = new Intl.DateTimeFormat(undefined, {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(new Date());
}

function localDateString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function loadDashboardData() {
  const offset = new Date().getTimezoneOffset();
  const query = new URLSearchParams({ offset_minutes: String(offset), local_date: localDateString() });
  const [summary, sessions, active] = await Promise.all([
    api(`/api/dashboard?${query}`),
    api('/api/sessions?limit=10'),
    api('/api/sessions/active'),
  ]);
  $('#productiveTime').textContent = summary.completed_sessions ? formatDuration(summary.productive_seconds) : 'No data yet';
  const coins = Number(summary.coin_balance || 0).toLocaleString();
  $('#coinBalance').textContent = coins;
  $('#coinBalanceCard').textContent = coins;
  coinRatesPer15Minutes = summary.coin_rates_per_15_minutes || {};
  $('#focusSessions').textContent = summary.completed_sessions
    ? `${summary.completed_sessions} ${summary.completed_sessions === 1 ? 'session' : 'sessions'}`
    : 'No data yet';
  lastDashboard = summary;
  lastSessions = sessions;
  renderGoal(summary);
  renderAchievements(summary);
  renderQuickStart(sessions);
  renderRecentSessions(sessions);
  if (active) renderSession(active);
  else showIdle();
  await loadAnalyticsData();
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  if (minutes) return `${minutes}m`;
  return `${total}s`;
}

function formatRangeDate(value, options = { month: 'short', day: 'numeric' }) {
  return new Intl.DateTimeFormat(undefined, options).format(new Date(`${value}T12:00:00`));
}

function analyticsQuery() {
  const params = new URLSearchParams({
    period: analyticsPeriod,
    anchor_date: analyticsAnchor,
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  });
  return params;
}

function setAnalyticsMetric(id, value) {
  const target = $(`#${id}`);
  if (target) target.textContent = value;
}

function renderAnalytics(analytics) {
  const stats = analytics.summary;
  $('#analyticsRange').textContent = `${formatRangeDate(analytics.start_date)} — ${formatRangeDate(analytics.end_date, { month: 'short', day: 'numeric', year: 'numeric' })}`;
  setAnalyticsMetric('analyticsFocusTime', formatDuration(stats.focus_seconds));
  setAnalyticsMetric('analyticsFocusMeta', `${stats.focus_sessions} completed ${stats.focus_sessions === 1 ? 'work session' : 'work sessions'}`);
  setAnalyticsMetric('analyticsBreakTime', formatDuration(stats.break_seconds));
  setAnalyticsMetric('analyticsBreakMeta', `${stats.break_sessions} manually tracked ${stats.break_sessions === 1 ? 'break' : 'breaks'}`);
  setAnalyticsMetric('analyticsConsistency', `${stats.active_day_rate_percent}%`);
  setAnalyticsMetric('analyticsConsistencyMeta', `${stats.active_focus_days} of ${stats.calendar_days} days · ${stats.average_focus_minutes_per_active_day ?? '—'}m average on active days`);
  setAnalyticsMetric('analyticsRating', stats.average_focus_rating === null ? '—' : `${Number(stats.average_focus_rating).toFixed(1)} / 5`);
  setAnalyticsMetric('analyticsRatingMeta', `${stats.focus_rating_samples} optional self-rating${stats.focus_rating_samples === 1 ? '' : 's'}`);
  setAnalyticsMetric('analyticsDistractions', String(stats.reported_distractions));
  setAnalyticsMetric('analyticsDistractionMeta', `${stats.distractions_per_focus_hour} per tracked focus hour`);
  setAnalyticsMetric('analyticsMedian', stats.median_focus_session_minutes === null ? '—' : `${stats.median_focus_session_minutes}m`);
  setAnalyticsMetric('analyticsVariation', `Daily variation · ${stats.focus_minutes_stddev_per_active_day ?? '—'}m σ`);
  const chart = $('#analyticsChart');
  $('#analyticsChartError').classList.add('hidden');
  chart.classList.add('hidden');
  chart.onerror = () => {
    chart.classList.add('hidden');
    $('#analyticsChartError').classList.remove('hidden');
  };
  chart.onload = () => chart.classList.remove('hidden');
  const chartQuery = analyticsQuery();
  chartQuery.set('theme', document.documentElement.dataset.theme || 'light');
  chart.src = `/api/analytics/chart?${chartQuery}`;
  lastAnalytics = analytics;
  renderNativeCharts(analytics);
  renderInsights(analytics, lastDashboard);
  updatePeriodNavigation();
}

async function loadAnalyticsData() {
  $('#analyticsRange').textContent = 'Gathering your tracked sessions…';
  try {
    const analytics = await api(`/api/analytics?${analyticsQuery()}`);
    renderAnalytics(analytics);
  } catch (error) {
    $('#analyticsRange').textContent = errorMessage(error, 'Your analysis is unavailable right now.');
    $('#analyticsChart').classList.add('hidden');
    $('#analyticsChartError').classList.remove('hidden');
    updatePeriodNavigation();
  }
}

function updatePeriodNavigation() {
  const today = localDateString();
  let isCurrent = analyticsAnchor >= today;
  if (analyticsPeriod === 'monthly') isCurrent = analyticsAnchor.slice(0, 7) >= today.slice(0, 7);
  if (analyticsPeriod === 'yearly') isCurrent = analyticsAnchor.slice(0, 4) >= today.slice(0, 4);
  $('#periodNext').disabled = isCurrent;
}

function moveAnalyticsPeriod(direction) {
  const anchor = new Date(`${analyticsAnchor}T12:00:00`);
  if (analyticsPeriod === 'weekly') anchor.setDate(anchor.getDate() + direction * 7);
  else if (analyticsPeriod === 'monthly') {
    anchor.setDate(1);
    anchor.setMonth(anchor.getMonth() + direction);
    const today = new Date(`${localDateString()}T12:00:00`);
    if (anchor.getFullYear() === today.getFullYear() && anchor.getMonth() === today.getMonth()) {
      anchor.setDate(today.getDate());
    } else if (direction < 0 || anchor < today) {
      anchor.setMonth(anchor.getMonth() + 1, 0);
    }
  } else {
    anchor.setMonth(0, 1);
    anchor.setFullYear(anchor.getFullYear() + direction);
    const today = new Date(`${localDateString()}T12:00:00`);
    if (anchor.getFullYear() === today.getFullYear()) anchor.setDate(today.getDate());
    else if (direction < 0 || anchor < today) anchor.setMonth(11, 31);
  }
  const todayString = localDateString();
  const anchorString = `${anchor.getFullYear()}-${String(anchor.getMonth() + 1).padStart(2, '0')}-${String(anchor.getDate()).padStart(2, '0')}`;
  if (anchorString > todayString) analyticsAnchor = todayString;
  else analyticsAnchor = anchorString;
  loadAnalyticsData();
}

async function logDistraction() {
  if (!currentSession || currentSession.type === 'break') return;
  if (currentSession.type === 'private') {
    currentSession.distraction_count = Number(currentSession.distraction_count || 0) + 1;
    $('#distractionCount').textContent = String(currentSession.distraction_count);
    return;
  }
  if (requestBusy) return;
  const button = $('#logDistractionBtn');
  requestBusy = true;
  button.disabled = true;
  $('#pauseBtn').disabled = true;
  $('#resumeBtn').disabled = true;
  $('#stopBtn').disabled = true;
  try {
    const updated = await api(`/api/sessions/${encodeURIComponent(currentSession.id)}/distractions`, { method: 'POST' });
    currentSession.distraction_count = updated.distraction_count;
    $('#distractionCount').textContent = String(currentSession.distraction_count);
  } catch (error) {
    setError(`Could not log that distraction: ${errorMessage(error)}`);
  } finally {
    requestBusy = false;
    button.disabled = false;
    $('#pauseBtn').disabled = false;
    $('#resumeBtn').disabled = false;
    $('#stopBtn').disabled = false;
  }
}

function renderRecentSessions(sessions) {
  const list = $('#recentSessions');
  list.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = 'No saved sessions yet. Private work is never included here.';
    list.append(empty);
    return;
  }
  for (const session of sessions) {
    const meta = SESSION_TYPES[session.type] || SESSION_TYPES.coding;
    const item = document.createElement('article');
    item.className = 'recent-session';
    const heading = document.createElement('h3');
    const mark = document.createElement('span');
    mark.className = 'recent-session__mark';
    mark.setAttribute('aria-hidden', 'true');
    heading.append(mark, document.createTextNode(session.title));
    const detail = document.createElement('p');
    detail.textContent = session.completion_note || session.task_description || meta.label;
    const status = document.createElement('span');
    status.className = 'badge';
    status.textContent = session.status === 'completed'
      ? `${session.status} · ${formatDuration(session.elapsed_seconds)} · +${Number(session.reward_coins || 0)} coins`
      : `${session.status} · ${formatDuration(session.elapsed_seconds)}`;
    item.append(heading, detail, status);
    list.append(item);
  }
}

function updateSessionType() {
  const type = $('#sessionType').value;
  const meta = SESSION_TYPES[type];
  const privacyHint = type === 'private'
    ? ' This session stays in this tab and is never saved.'
    : '';
  const rewardHint = type === 'private' || type === 'break'
    ? ' No coins are awarded for this session type.'
    : ` Completed sessions earn ${Number(coinRatesPer15Minutes[type] || 0)} coins per 15 tracked minutes.`;
  $('#sessionTypeHint').textContent = `${meta.hint}${privacyHint}${rewardHint} Coins use the timer and your selected type; cursor activity is not monitored.`;
  $('#sessionTaskLabel').textContent = meta.task;
  $('#sessionGoalLabel').textContent = `${meta.goal} (optional)`;
  $('#sessionTask').placeholder = meta.task;
  $('#sessionGoal').placeholder = `What would you like to complete?`;
  $('#modalTitle').textContent = `${meta.icon} ${meta.label} session`;
  $('#sessionDuration').disabled = false;
  $('#sessionTask').autocomplete = 'off';
  $('#sessionGoal').autocomplete = 'off';
  setError('');
}

function openModal(prefill = null) {
  if (requestBusy || (currentSession && ['running', 'paused'].includes(currentSession.status))) return;
  const preset = prefill && typeof prefill === 'object' && prefill.type ? prefill : null;
  $('#sessionError').textContent = '';
  $('#sessionType').value = preset?.type || 'coding';
  $('#sessionTask').value = preset?.task || '';
  $('#sessionGoal').value = preset?.goal || '';
  updateSessionType();
  if (preset?.duration) $('#sessionDuration').value = String(preset.duration);
  $('#modalOverlay').classList.remove('hidden');
  $('#sessionType').focus();
}

function closeModal() {
  $('#modalOverlay').classList.add('hidden');
}

async function startSession() {
  if (requestBusy) return;
  const type = $('#sessionType').value;
  const meta = SESSION_TYPES[type];
  if (!meta) {
    setError('Choose a valid session type.');
    return;
  }
  const task = $('#sessionTask').value.trim();
  const goal = $('#sessionGoal').value.trim();
  const chosenDuration = Number($('#sessionDuration').value);
  const session = {
    type,
    title: `${meta.label} session`,
    task_description: task,
    goal,
    duration_minutes: chosenDuration || null,
    status: 'running',
    elapsed_seconds: 0,
  };

  requestBusy = true;
  $('#modalStartBtn').disabled = true;
  setError('');
  try {
    if (type === 'private') {
      // Do not call an API or storage API from this branch.
      session.id = `private-${crypto.randomUUID()}`;
    } else {
      const payload = {
        session_type: type,
        title: session.title,
        task_description: task,
        goal,
        duration_minutes: chosenDuration || null,
      };
      const saved = await api('/api/sessions', { method: 'POST', body: JSON.stringify(payload) });
      Object.assign(session, saved);
    }
    closeModal();
    renderSession(session);
    setError('');
    $('#sessions').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    setError(errorMessage(error, 'Session could not start. Your form entries are still here; please try again.'));
  } finally {
    requestBusy = false;
    $('#modalStartBtn').disabled = false;
  }
}

function createRecordingId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  const suffix = String(Date.now()).padStart(12, '0').slice(-12);
  return `00000000-0000-4000-8000-${suffix}`;
}

async function startCompanionRecording(recordingId) {
  companionTrackingId = recordingId;
  try {
    await companionFetch('/api/recordings/start', {
      method: 'POST',
      body: JSON.stringify({ recording_id: recordingId, session_type: currentSession.type }),
    });
  } catch (error) {
    // A timed-out response may still have started tracking; make a best-effort stop.
    try {
      await companionFetch(`/api/recordings/${encodeURIComponent(recordingId)}/stop`, { method: 'POST' });
    } catch { /* The companion's heartbeat timeout is the final safeguard. */ }
    companionTrackingId = '';
    throw error;
  }
  clearInterval(companionHeartbeatTick);
  companionHeartbeatTick = setInterval(async () => {
    if (companionTrackingId !== recordingId) return;
    try {
      await companionFetch(`/api/recordings/${encodeURIComponent(recordingId)}/heartbeat`, { method: 'POST' });
    } catch (error) {
      clearInterval(companionHeartbeatTick);
      companionHeartbeatTick = null;
      companionConnected = false;
      appReportMessage = `Companion connection lost: ${errorMessage(error)}. It will stop tracking automatically if this tab closes.`;
      updateRecordingUI();
    }
  }, 10000);
}

async function stopCompanionRecording(recordingId) {
  if (companionTrackingId !== recordingId) return false;
  clearInterval(companionHeartbeatTick);
  companionHeartbeatTick = null;
  try {
    const response = await companionFetch(`/api/recordings/${encodeURIComponent(recordingId)}/stop`, { method: 'POST' });
    const result = await response.json();
    appActivityReportId = recordingId;
    appReportMessage = result.status === 'completed'
      ? ''
      : 'The companion timeline was interrupted. Its report contains the app intervals recorded before it stopped.';
    return true;
  } catch (error) {
    appActivityReportId = recordingId;
    appReportMessage = `The video stopped, but the companion did not confirm its report: ${errorMessage(error)}`;
    return false;
  } finally {
    companionTrackingId = '';
    updateRecordingUI();
    if (appActivityReportId) void loadActivityReports({ reveal: false, silent: true });
  }
}

async function finishRecording(capture) {
  if (activeRecorder !== capture) return;
  capture.stream.getTracks().forEach(track => track.stop());
  if (capture.companionTracked) await stopCompanionRecording(capture.recordingId);
  activeRecorder = null;
  completedRecording = capture.chunks.length ? capture : null;
  recordingState = completedRecording ? 'ready' : 'idle';
  const stoppedMessage = completedRecording
    ? (appActivityReportId
      ? 'Video and app timeline stopped. The separate app activity Excel is ready to download; neither file was uploaded.'
      : 'Screen recording stopped. Download it or discard it; it has not been uploaded.')
    : 'Screen recording stopped with no video data to keep.';
  updateRecordingUI(appReportMessage ? `${stoppedMessage} ${appReportMessage}` : stoppedMessage);
  // Ending the share from the browser toolbar never presses the stop button,
  // so finish the live polling and show the final app time here too.
  if (capture.companionTracked) {
    stopLiveActivityPolling(capture.recordingId, currentSession?.type || 'coding');
  }
}

async function failRecording(capture, message) {
  if (activeRecorder !== capture) return;
  activeRecorder = null;
  capture.stream.getTracks().forEach(track => track.stop());
  capture.chunks.length = 0;
  if (capture.companionTracked) await stopCompanionRecording(capture.recordingId);
  clearInterval(activityPollTick);
  activityPollTick = null;
  recordingState = 'error';
  updateRecordingUI(message);
}

async function startScreenRecording() {
  if (!currentSession || currentSession.type === 'private') {
    updateRecordingUI('Screen recording is unavailable in Private Mode.');
    return;
  }
  if (!$('#recordingConsent').checked) {
    updateRecordingUI('Check the consent box before starting screen recording.');
    return;
  }
  const trackAppActivity = $('#recordingAppActivityConsent').checked;
  if (trackAppActivity && !companionConnected) {
    updateRecordingUI('Connect the Windows companion before starting a recording with app activity tracking.');
    return;
  }
  if (!navigator.mediaDevices?.getDisplayMedia) {
    recordingState = 'error';
    updateRecordingUI('This browser does not support screen sharing. Timer state is unchanged.');
    return;
  }
  if (typeof MediaRecorder === 'undefined') {
    recordingState = 'error';
    updateRecordingUI('This browser does not support screen recording. Timer state is unchanged.');
    return;
  }
  if (recordingState === 'recording' || recordingState === 'requesting' || completedRecording || appActivityReportId) return;

  recordingState = 'requesting';
  updateRecordingUI();
  let requestedStream = null;
  let capture = null;
  let companionStarted = false;
  const recordingId = createRecordingId();
  try {
    // This call is deliberately made only from the explicit Start screen recording click.
    const stream = requestedStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    if (trackAppActivity) {
      await startCompanionRecording(recordingId);
      companionStarted = true;
    }
    let mimeType = '';
    if (typeof MediaRecorder.isTypeSupported === 'function') {
      if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) mimeType = 'video/webm;codecs=vp9';
      else if (MediaRecorder.isTypeSupported('video/webm;codecs=vp8')) mimeType = 'video/webm;codecs=vp8';
      else if (MediaRecorder.isTypeSupported('video/webm')) mimeType = 'video/webm';
    }
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    capture = {
      stream, recorder, chunks: [], recordingId, companionTracked: companionStarted,
      mimeType: recorder.mimeType || mimeType || 'video/webm',
    };
    activeRecorder = capture;
    recorder.addEventListener('dataavailable', event => {
      if (event.data?.size && activeRecorder === capture) capture.chunks.push(event.data);
    });
    recorder.addEventListener('error', () => {
      void failRecording(capture, 'The recording failed. Its video was discarded; the timer is unchanged.');
    }, { once: true });
    recorder.addEventListener('stop', () => {
      void finishRecording(capture);
    }, { once: true });
    stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
      if (activeRecorder === capture && recorder.state !== 'inactive') {
        stopScreenRecording('Screen sharing ended; recording stopped automatically.');
      }
    }, { once: true }));
    recorder.start(1000);
    recordingState = 'recording';
    updateRecordingUI();
  } catch (error) {
    requestedStream?.getTracks().forEach(track => track.stop());
    if (capture && activeRecorder === capture) {
      activeRecorder = null;
      capture.chunks.length = 0;
    }
    if (companionStarted) await stopCompanionRecording(recordingId);
    recordingState = 'error';
    const denied = ['NotAllowedError', 'AbortError'].includes(error?.name);
    const missing = error?.name === 'NotFoundError';
    updateRecordingUI(companionStarted && !activeRecorder
      ? `Recording could not start after app tracking began: ${errorMessage(error, 'browser error')}. The app report is still available.`
      : denied
      ? 'Screen-share permission was denied or cancelled. Timer state is unchanged; recording did not start.'
      : missing
        ? 'No screen or window was selected. Timer state is unchanged.'
      : `Screen recording could not start: ${errorMessage(error, 'browser error')}`);
  }
}

function stopScreenRecording(message = '') {
  if (!activeRecorder) return;
  const capture = activeRecorder;
  if (capture.recorder.state === 'inactive') return;
  recordingState = 'stopping';
  updateRecordingUI(message || 'Stopping screen recording…');
  try {
    capture.recorder.stop();
  } catch (error) {
    capture.stream.getTracks().forEach(track => track.stop());
    capture.chunks.length = 0;
    activeRecorder = null;
    if (capture.companionTracked) void stopCompanionRecording(capture.recordingId);
    recordingState = 'error';
    updateRecordingUI(`Could not stop screen recording cleanly: ${errorMessage(error)}`);
  }
}

function downloadRecording() {
  if (!completedRecording) return;
  const blob = new Blob(completedRecording.chunks, { type: completedRecording.mimeType });
  if (!blob.size) {
    discardRecording('The recording was empty and has been discarded.');
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `focusforge-${completedRecording.recordingId || createRecordingId()}.webm`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  void discardRecording('Recording downloaded to your device by your request. No copy was uploaded.');
}

async function downloadAppActivityReport(recordingId = appActivityReportId) {
  if (!recordingId) return;
  const filename = `focusforge-${recordingId}-app-activity.xlsx`;
  try {
    // Prefer the server-side route which delivers the enriched workbook
    // (includes work score, productivity %, category, weight per app).
    // The backend proxies the request through the authenticated session
    // so no CORS hop to the companion is needed here.
    if (companionPairingCode) {
      const params = new URLSearchParams({ companion_token: companionPairingCode });
      const response = await fetch(
        `/api/activity/export/${encodeURIComponent(recordingId)}?${params}`,
        { credentials: 'same-origin', cache: 'no-store' }
      );
      if (response.status === 401) { window.location.assign('/login'); return; }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(apiErrorMessage(data, response.status));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      appReportMessage = 'Activity report downloaded. It includes your work score, app categories, and productivity breakdown. The companion copy remains until you delete it.';
    } else {
      // Fallback: direct companion fetch (no backend session required)
      const response = await companionFetch(`/api/recordings/${encodeURIComponent(recordingId)}/export.xlsx`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      appReportMessage = 'Matching Excel file downloaded. Its local companion copy remains until you delete it.';
    }
  } catch (error) {
    appReportMessage = `Could not download the app activity Excel file: ${errorMessage(error)}`;
  }
  updateRecordingUI();
}

async function saveRecordingBundle() {
  if (!completedRecording || !appActivityReportId) return;
  const recordingId = completedRecording.recordingId;
  if (!window.showDirectoryPicker) {
    downloadRecording();
    await downloadAppActivityReport();
    appReportMessage = 'Both files were sent to your browser downloads. If it asks for a location, choose the same folder for each.';
    updateRecordingUI();
    return;
  }
  let directory;
  try {
    directory = await window.showDirectoryPicker({ id: 'focusforge-recordings', mode: 'readwrite' });
  } catch (error) {
    if (error?.name === 'AbortError') return;
    appReportMessage = `Could not choose a folder: ${errorMessage(error)}`;
    updateRecordingUI();
    return;
  }
  try {
    const params = new URLSearchParams({ companion_token: companionPairingCode });
    const reportResponse = await fetch(
      `/api/activity/export/${encodeURIComponent(recordingId)}?${params}`,
      { credentials: 'same-origin', cache: 'no-store' }
    );
    if (!reportResponse.ok) {
      const data = await reportResponse.json().catch(() => ({}));
      throw new Error(apiErrorMessage(data, reportResponse.status));
    }
    const reportBlob = await reportResponse.blob();
    const videoBlob = new Blob(completedRecording.chunks, { type: completedRecording.mimeType });
    if (!videoBlob.size || !reportBlob.size) throw new Error('The video or Excel report is empty.');
    const saveFile = async (name, blob) => {
      const handle = await directory.getFileHandle(name, { create: true });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
    };
    await saveFile(`focusforge-${recordingId}.webm`, videoBlob);
    await saveFile(`focusforge-${recordingId}-app-activity.xlsx`, reportBlob);
    await discardRecording('Video and matching app activity Excel were saved together in the selected folder.');
  } catch (error) {
    appReportMessage = `Could not save both files together: ${errorMessage(error)}. You can still download them separately.`;
    updateRecordingUI();
  }
}

async function deleteAppActivityReport() {
  if (!appActivityReportId) return;
  try {
    await companionFetch(`/api/recordings/${encodeURIComponent(appActivityReportId)}/delete`, { method: 'DELETE' });
    appActivityReportId = '';
    appReportMessage = 'The companion copy was deleted from this device.';
    void loadActivityReports({ silent: true });
  } catch (error) {
    appReportMessage = `Could not delete the local app report: ${errorMessage(error)}`;
  }
  updateRecordingUI();
}

async function discardRecording(message = 'Recording discarded from this tab.') {
  if (activeRecorder) {
    const capture = activeRecorder;
    activeRecorder = null;
    capture.stream.getTracks().forEach(track => track.stop());
    if (capture.recorder.state !== 'inactive') capture.recorder.stop();
    capture.chunks.length = 0;
    if (capture.companionTracked) await stopCompanionRecording(capture.recordingId);
  }
  if (completedRecording) completedRecording.chunks.length = 0;
  completedRecording = null;
  recordingState = 'idle';
  $('#recordingConsent').checked = false;
  updateRecordingUI(message);
}

async function transitionSession(action) {
  if (!currentSession || requestBusy) return;
  const session = currentSession;
  if (session.type === 'private') {
    if (action === 'pause') {
      elapsedAtAnchor = currentElapsed();
      session.status = 'paused';
      session.elapsed_seconds = elapsedAtAnchor;
      stopClock();
      renderSession(session);
    } else if (action === 'resume') {
      session.elapsed_seconds = elapsedAtAnchor;
      session.status = 'running';
      renderSession(session);
    } else if (action === 'stop') {
      showIdle();
    }
    return;
  }

  if (action === 'stop' && (recordingState === 'recording' || recordingState === 'requesting' || recordingState === 'stopping')) {
    setError('Stop the screen recording first, then download or discard it before ending the session.');
    return;
  }
  if (action === 'stop' && completedRecording) {
    setError('Download or discard the stopped screen recording before ending the session.');
    return;
  }
  if (action === 'stop' && appActivityReportId) {
    setError('Download or delete the companion app report before ending the session.');
    return;
  }

  requestBusy = true;
  $('#pauseBtn').disabled = true;
  $('#resumeBtn').disabled = true;
  $('#stopBtn').disabled = true;
  try {
    const request = { method: 'POST' };
    if (action === 'stop') request.body = JSON.stringify({
      completion_note: $('#completionNote').value,
      focus_rating: $('#focusRating').value ? Number($('#focusRating').value) : null,
    });
    const updated = await api(`/api/sessions/${encodeURIComponent(session.id)}/${action}`, request);
    if (action === 'stop') {
      showIdle();
      await loadDashboardData();
    } else renderSession(updated);
  } catch (error) {
    setError(errorMessage(error));
  } finally {
    requestBusy = false;
    $('#pauseBtn').disabled = false;
    $('#resumeBtn').disabled = false;
    $('#stopBtn').disabled = false;
  }
}

function openFullSessionPanel() {
  const section = $('#sessions');
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  section.focus({ preventScroll: true });
}

function installFloatingDrag() {
  const floater = $('#sessionFloater');
  const handle = $('#sessionFloaterHandle');
  let drag = null;
  handle.addEventListener('pointerdown', event => {
    if (pictureInPictureWindow && handle.ownerDocument === pictureInPictureWindow.document) return;
    if (event.button !== 0) return;
    const rect = floater.getBoundingClientRect();
    drag = { pointerId: event.pointerId, offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top };
    handle.setPointerCapture(event.pointerId);
    floater.style.left = `${rect.left}px`;
    floater.style.top = `${rect.top}px`;
    floater.style.right = 'auto';
    floater.style.bottom = 'auto';
  });
  handle.addEventListener('pointermove', event => {
    if (pictureInPictureWindow && handle.ownerDocument === pictureInPictureWindow.document) return;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const maxLeft = Math.max(0, window.innerWidth - floater.offsetWidth);
    const maxTop = Math.max(0, window.innerHeight - floater.offsetHeight);
    floater.style.left = `${Math.max(0, Math.min(maxLeft, event.clientX - drag.offsetX))}px`;
    floater.style.top = `${Math.max(0, Math.min(maxTop, event.clientY - drag.offsetY))}px`;
  });
  const finishDrag = event => {
    if (drag?.pointerId === event.pointerId) drag = null;
  };
  handle.addEventListener('pointerup', finishDrag);
  handle.addEventListener('pointercancel', finishDrag);
  window.addEventListener('resize', () => {
    if (floater.classList.contains('hidden') || !floater.style.left) return;
    const maxLeft = Math.max(0, window.innerWidth - floater.offsetWidth);
    const maxTop = Math.max(0, window.innerHeight - floater.offsetHeight);
    floater.style.left = `${Math.min(maxLeft, parseFloat(floater.style.left) || 0)}px`;
    floater.style.top = `${Math.min(maxTop, parseFloat(floater.style.top) || 0)}px`;
  });
}

function hideFloatingIndicator() {
  floaterHidden = true;
  if (pictureInPictureWindow) pictureInPictureWindow.close();
  updateFloatingIndicator();
}

function restoreFloatingIndicator() {
  floaterHidden = false;
  updateFloatingIndicator();
}

async function popOutFloatingIndicator() {
  const popup = window.documentPictureInPicture;
  if (!popup?.requestWindow) {
    setError('A separate floating timer window is not supported in this browser. The in-page timer is still available.');
    return;
  }
  if (pictureInPictureWindow) {
    pictureInPictureWindow.focus();
    return;
  }
  try {
    const pip = await popup.requestWindow({ width: 370, height: 330 });
    pictureInPictureWindow = pip;
    pip.document.documentElement.dataset.theme = document.documentElement.dataset.theme || 'light';
    pip.document.body.className = 'pip-overlay';
    for (const stylesheet of document.querySelectorAll('link[rel="stylesheet"]')) {
      const link = pip.document.createElement('link');
      link.rel = 'stylesheet';
      link.href = stylesheet.href;
      pip.document.head.append(link);
    }
    const floater = document.getElementById('sessionFloater');
    pip.document.body.append(floater);
    floater.classList.remove('hidden');
    pip.addEventListener('pagehide', () => {
      document.body.append(floater);
      pictureInPictureWindow = null;
      updateFloatingIndicator();
    }, { once: true });
    updateFloatingIndicator();
  } catch (error) {
    pictureInPictureWindow = null;
    setError(`Could not open the floating timer: ${errorMessage(error, 'browser window error')}`);
  }
}

function getThemePreference() {
  const saved = document.cookie.match(/(?:^|;\s*)focusforge_theme=(dark|light)(?:;|$)/)?.[1];
  return saved || (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function applyTheme(theme, persist = true) {
  const selected = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = selected;
  const toggle = $('#themeToggle');
  toggle.setAttribute('aria-pressed', String(selected === 'dark'));
  toggle.title = `Switch to ${selected === 'dark' ? 'light' : 'dark'} mode`;
  $('#themeToggleLabel').textContent = selected === 'dark' ? 'Light mode' : 'Dark mode';
  toggle.querySelector('.theme-toggle__icon').textContent = selected === 'dark' ? '☼' : '☾';
  if (persist) {
    // This cookie stores only the user's visual preference, never session or Private Mode data.
    document.cookie = `focusforge_theme=${selected}; Max-Age=31536000; Path=/; SameSite=Lax`;
  }
  if (lastAnalytics) renderNativeCharts(lastAnalytics);
  if (pictureInPictureWindow) pictureInPictureWindow.document.documentElement.dataset.theme = selected;
  if (currentUser) {
    const chart = $('#analyticsChart');
    if (chart.src) {
      const query = analyticsQuery();
      query.set('theme', selected);
      chart.src = `/api/analytics/chart?${query}`;
    }
  }
}

function initializeTheme() {
  applyTheme(getThemePreference(), false);
}

async function signOut() {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } finally {
    window.location.assign('/login');
  }
}

function openSidebar() {
  $('#sidebar').classList.add('is-open');
  $('#sidebarToggle').setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
  $('#sidebar').classList.remove('is-open');
  $('#sidebarToggle').setAttribute('aria-expanded', 'false');
}

async function initializeDashboard() {
  initializeTheme();
  updateDate();
  const statusText = $('#statusText');
  try {
    currentUser = await api('/api/auth/me');
    $('#userEmail').textContent = currentUser.email;
    $('#userAvatar').textContent = currentUser.email.slice(0, 1).toUpperCase();
    statusText.textContent = 'Manual tracking';
    $('#statusDot').className = 'status-dot status-dot--ok';
    await loadDashboardData();
  } catch (error) {
    if (error.message !== 'Please sign in again.') {
      statusText.textContent = 'Backend unavailable';
      $('#statusDot').className = 'status-dot status-dot--error';
      $('#productiveTime').textContent = 'Unavailable';
      $('#focusSessions').textContent = 'Unavailable';
      $('#recentSessions').replaceChildren(Object.assign(document.createElement('p'), {
        className: 'empty-state', textContent: 'Could not load saved sessions. Check the server and reload.',
      }));
    }
  }

  $('#startSessionBtn').addEventListener('click', () => openModal());
  $('#startSessionBtn2').addEventListener('click', () => openModal());
  $('#modalCancelBtn').addEventListener('click', closeModal);
  $('#modalStartBtn').addEventListener('click', startSession);
  $('#sessionType').addEventListener('change', updateSessionType);
  $('#pauseBtn').addEventListener('click', () => transitionSession('pause'));
  $('#resumeBtn').addEventListener('click', () => transitionSession('resume'));
  $('#stopBtn').addEventListener('click', () => transitionSession('stop'));
  $('#floaterPauseBtn').addEventListener('click', () => transitionSession('pause'));
  $('#floaterResumeBtn').addEventListener('click', () => transitionSession('resume'));
  $('#floaterStopBtn').addEventListener('click', () => transitionSession('stop'));
  $('#floaterOpenBtn').addEventListener('click', openFullSessionPanel);
  $('#floaterHideBtn').addEventListener('click', hideFloatingIndicator);
  $('#floaterRestoreBtn').addEventListener('click', restoreFloatingIndicator);
  $('#floaterPopoutBtn').addEventListener('click', popOutFloatingIndicator);
  $('#themeToggle').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  $('#analyticsPeriod').addEventListener('change', event => {
    analyticsPeriod = event.target.value;
    analyticsAnchor = localDateString();
    loadAnalyticsData();
  });
  $('#periodPrevious').addEventListener('click', () => moveAnalyticsPeriod(-1));
  $('#periodNext').addEventListener('click', () => moveAnalyticsPeriod(1));
  window.addEventListener('resize', scheduleChartRerender);
  $('#logDistractionBtn').addEventListener('click', logDistraction);
  $('#recordingConsent').addEventListener('change', () => updateRecordingUI());
  $('#recordingAppActivityConsent').addEventListener('change', () => {
    if (!$('#recordingAppActivityConsent').checked) {
      $('#companionPairingCode').value = '';
      companionPairingCode = '';
      companionConnected = false;
      window.sessionStorage?.removeItem('focusforge_companion_code');
      $('#companionConnectionStatus').textContent = 'App tracking is off. No app names are collected.';
    }
    updateRecordingUI();
  });
  $('#companionConnectBtn').addEventListener('click', () => { void connectCompanion(); });
  $('#recordingStartBtn').addEventListener('click', startScreenRecording);
  $('#recordingStopBtn').addEventListener('click', () => stopScreenRecording());
  $('#recordingDownloadBtn').addEventListener('click', downloadRecording);
  $('#recordingDiscardBtn').addEventListener('click', () => discardRecording());
  $('#recordingReportDownloadBtn').addEventListener('click', () => { void downloadAppActivityReport(); });
  $('#recordingBundleSaveBtn').addEventListener('click', () => { void saveRecordingBundle(); });
  $('#recordingReportDeleteBtn').addEventListener('click', () => { void deleteAppActivityReport(); });
  $('#activityReportsRefreshBtn').addEventListener('click', () => { void loadActivityReports({ reveal: true }); });
  $('#goalForm').addEventListener('submit', saveGoal);
  $$('#quickStartRow [data-preset]').forEach(button => {
    button.addEventListener('click', () => openModal({
      type: button.dataset.preset,
      duration: Number(button.dataset.minutes) || undefined,
    }));
  });
  $('#repeatLastBtn').addEventListener('click', repeatLastSession);
  $('#shortcutHintBtn').addEventListener('click', openShortcuts);
  $('#shortcutCloseBtn').addEventListener('click', closeShortcuts);
  $('#shortcutOverlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) closeShortcuts();
  });
  installKeyboardShortcuts();
  const savedPairingCode = window.sessionStorage?.getItem('focusforge_companion_code') || '';
  if (savedPairingCode) {
    $('#companionPairingCode').value = savedPairingCode;
    void connectCompanion(savedPairingCode, true);
  }
  installFloatingDrag();
  $('#logoutBtn').addEventListener('click', signOut);
  $('#sidebarToggle').addEventListener('click', () => {
    $('#sidebar').classList.contains('is-open') ? closeSidebar() : openSidebar();
  });
  $$('.nav-item').forEach(item => item.addEventListener('click', () => {
    $$('.nav-item').forEach(link => {
      link.classList.remove('nav-item--active');
      link.removeAttribute('aria-current');
    });
    item.classList.add('nav-item--active');
    item.setAttribute('aria-current', 'page');
    if (window.innerWidth <= 768) closeSidebar();
  }));
  $('#modalOverlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) closeModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeModal();
  });
  document.addEventListener('click', event => {
    const sidebar = $('#sidebar');
    const toggle = $('#sidebarToggle');
    if (window.innerWidth <= 768 && sidebar.classList.contains('is-open')
        && !sidebar.contains(event.target) && !toggle.contains(event.target)) closeSidebar();
  });
  window.addEventListener('beforeunload', () => {
    stopClock();
    if (companionTrackingId && companionPairingCode && navigator.sendBeacon) {
      try {
        const id = companionTrackingId;
        const body = new Blob([JSON.stringify({ pairing_code: companionPairingCode })], { type: 'text/plain' });
        navigator.sendBeacon(`${COMPANION_ORIGIN}/api/recordings/${encodeURIComponent(id)}/stop-beacon`, body);
      } catch { /* The companion heartbeat timeout remains the fallback. */ }
    }
    clearInterval(companionHeartbeatTick);
    companionHeartbeatTick = null;
    if (activeRecorder) {
      const capture = activeRecorder;
      activeRecorder = null;
      capture.chunks.length = 0;
      capture.stream.getTracks().forEach(track => track.stop());
      if (capture.recorder.state !== 'inactive') capture.recorder.stop();
    }
    if (completedRecording) completedRecording.chunks.length = 0;
  }, { once: true });
}

document.addEventListener('DOMContentLoaded', initializeDashboard);

/* ═══════════════════════════════════════════════════════════════════════════
   SCREEN ACTIVITY — LIVE APP TIMELINE & WORK SCORE
   Records only foreground executable basenames from the Windows companion.
   No screen pixels, window titles, URLs, or keystrokes are ever captured.
═══════════════════════════════════════════════════════════════════════════ */

const APP_CATEGORY_COLORS = {
  productive: '#4ade80',   // green
  neutral:    '#94a3b8',   // slate
  distraction:'#f87171',   // red
};

// State for the live timeline module
let activityPollTick = null;
let lastTimelineData = null;
let workScoreData = null;

// Colour palette for the per-app bar segments
const APP_PALETTE = [
  '#6366f1', '#8b5cf6', '#ec4899', '#f97316', '#14b8a6',
  '#0ea5e9', '#a3e635', '#f59e0b', '#10b981', '#e11d48',
];

function appColor(index) {
  return APP_PALETTE[index % APP_PALETTE.length];
}

/* ─── Timeline Renderer ─────────────────────────────────────────────────── */

function renderAppTimeline(intervals, currentApp) {
  const container = document.getElementById('appTimelineChart');
  const legend = document.getElementById('appTimelineLegend');
  const currentAppEl = document.getElementById('liveCurrentApp');
  renderAppDonut(intervals || []);
  if (!container) return;

  if (currentAppEl && currentApp) {
    currentAppEl.textContent = currentApp;
    currentAppEl.parentElement?.classList.remove('hidden');
  }

  if (!intervals || !intervals.length) {
    container.innerHTML = '<p class="timeline-empty">Waiting for app activity…</p>';
    if (legend) legend.innerHTML = '';
    return;
  }

  const total = intervals.reduce((sum, iv) => sum + iv.elapsed_seconds, 0);
  if (total === 0) {
    container.innerHTML = '<p class="timeline-empty">No app activity recorded yet.</p>';
    return;
  }

  // Build stacked horizontal bar
  const bar = document.createElement('div');
  bar.className = 'timeline-bar';
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', 'App usage timeline');

  const legendItems = [];
  intervals.forEach((iv, idx) => {
    const pct = (iv.elapsed_seconds / total) * 100;
    if (pct < 0.5) return; // skip tiny slivers
    const seg = document.createElement('div');
    seg.className = 'timeline-segment';
    const cat = iv.category || 'neutral';
    const color = cat === 'productive' ? APP_CATEGORY_COLORS.productive
      : cat === 'distraction' ? APP_CATEGORY_COLORS.distraction
      : appColor(idx);
    seg.style.cssText = `width:${pct.toFixed(2)}%;background:${color};`;
    seg.title = `${iv.app_name}: ${formatDuration(iv.elapsed_seconds)} (${cat})`;
    bar.appendChild(seg);
    legendItems.push({ name: iv.app_name, color, seconds: iv.elapsed_seconds, cat });
  });

  container.replaceChildren(bar);

  // Legend
  if (legend) {
    legend.replaceChildren();
    legendItems.forEach(item => {
      const row = document.createElement('div');
      row.className = 'timeline-legend-item';
      const dot = document.createElement('span');
      dot.className = 'legend-dot';
      dot.style.background = item.color;
      const label = document.createElement('span');
      label.className = 'legend-label';
      label.textContent = `${item.name} — ${formatDuration(item.seconds)} (${Math.round(item.seconds / total * 100)}%)`;
      const badge = document.createElement('span');
      badge.className = `legend-badge legend-badge--${item.cat}`;
      badge.textContent = item.cat;
      row.append(dot, label, badge);
      legend.appendChild(row);
    });
  }
}

/* ─── Work Score Card Renderer ──────────────────────────────────────────── */

function renderWorkScore(scoreData) {
  const panel = document.getElementById('workScorePanel');
  if (!panel) return;
  panel.classList.remove('hidden');
  workScoreData = scoreData;

  const score = scoreData.score ?? 0;
  const label = scoreData.label ?? 'Unknown';
  const multiplier = scoreData.coin_multiplier ?? 1.0;

  // Score ring
  const ring = document.getElementById('workScoreRing');
  if (ring) {
    ring.textContent = String(score);
    ring.className = 'score-ring ' + (
      score >= 90 ? 'score-ring--deep' :
      score >= 75 ? 'score-ring--focused' :
      score >= 55 ? 'score-ring--moderate' :
      score >= 35 ? 'score-ring--distracted' : 'score-ring--offtask'
    );
  }
  const scoreLabel = document.getElementById('workScoreLabel');
  if (scoreLabel) scoreLabel.textContent = label;

  const multiplierEl = document.getElementById('workScoreMultiplier');
  if (multiplierEl) multiplierEl.textContent = `${multiplier}× coin multiplier`;

  // Stats row
  setScoreStat('scoreProductiveSecs', formatDuration(scoreData.productive_seconds || 0));
  setScoreStat('scoreDistractionSecs', formatDuration(scoreData.distraction_seconds || 0));
  setScoreStat('scoreNeutralSecs', formatDuration(scoreData.neutral_seconds || 0));

  // Breakdown bars
  renderBreakdownBars(scoreData.app_breakdown || []);
}

function setScoreStat(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderBreakdownBars(breakdown) {
  const container = document.getElementById('scoreBreakdownBars');
  if (!container) return;
  container.replaceChildren();
  const total = breakdown.reduce((s, b) => s + b.elapsed_seconds, 0) || 1;
  breakdown.slice(0, 10).forEach((item, idx) => {
    const pct = (item.elapsed_seconds / total * 100).toFixed(1);
    const row = document.createElement('div');
    row.className = 'breakdown-row';
    const nameEl = document.createElement('span');
    nameEl.className = 'breakdown-name';
    nameEl.textContent = item.app_name;
    const barWrap = document.createElement('div');
    barWrap.className = 'breakdown-bar-wrap';
    const bar = document.createElement('div');
    bar.className = 'breakdown-bar';
    const color = item.category === 'productive' ? APP_CATEGORY_COLORS.productive
      : item.category === 'distraction' ? APP_CATEGORY_COLORS.distraction
      : APP_CATEGORY_COLORS.neutral;
    bar.style.cssText = `width:${pct}%;background:${color};`;
    bar.setAttribute('aria-valuenow', pct);
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    bar.role = 'progressbar';
    barWrap.appendChild(bar);
    const timeEl = document.createElement('span');
    timeEl.className = 'breakdown-time';
    timeEl.textContent = formatDuration(item.elapsed_seconds);
    row.append(nameEl, barWrap, timeEl);
    container.appendChild(row);
  });
}

/* ─── Live Polling ──────────────────────────────────────────────────────── */

async function pollLiveTimeline() {
  if (!companionTrackingId || !companionPairingCode) return;
  try {
    const resp = await companionFetch(
      `/api/recordings/${encodeURIComponent(companionTrackingId)}/intervals-live`
    );
    const data = await resp.json();
    lastTimelineData = data;

    // Classify each interval using the session type
    const sessionType = currentSession?.type || 'coding';
    const intervals = await intervalsWithCategories(data.intervals, sessionType);
    renderAppTimeline(intervals, data.current_app);

    // Show live score estimate
    const liveScore = estimateLiveScore(intervals);
    const liveScoreEl = document.getElementById('liveWorkScore');
    const liveScoreLabelEl = document.getElementById('liveWorkScoreLabel');
    if (liveScoreEl) liveScoreEl.textContent = String(liveScore.score);
    if (liveScoreLabelEl) liveScoreLabelEl.textContent = liveScore.label;

    document.getElementById('activityPanel')?.classList.remove('hidden');
  } catch {
    // Companion unreachable — silently skip this poll
  }
}

/* ─── Client-side classifier (mirrors backend app_classifier.py) ─────────
   Only executable basenames. No screen content.                           */

const CLIENT_ALWAYS_DISTRACTION = new Set([
  'discord.exe','telegram.exe','whatsapp.exe','spotify.exe',
  'steam.exe','epicgameslauncher.exe','battle.net.exe','origin.exe',
  'leagueclient.exe','csgo.exe','valorant.exe',
]);
const CLIENT_NEUTRAL = new Set([
  'explorer.exe','searchapp.exe','searchhost.exe','lockapp.exe',
  'logonui.exe','dwm.exe','desktop','unavailable app','unknown app',
  'systemsettings.exe','settingssynchost.exe','taskmgr.exe','perfmon.exe',
]);
const CLIENT_PRODUCTIVE = {
  coding: new Set([
    'code.exe','code - insiders.exe','pycharm64.exe','idea64.exe',
    'webstorm64.exe','clion64.exe','rider64.exe','goland64.exe',
    'devenv.exe','atom.exe','sublime_text.exe','notepad++.exe',
    'vim.exe','nvim.exe','gvim.exe','emacs.exe',
    'windowsterminal.exe','cmd.exe','powershell.exe','pwsh.exe',
    'bash.exe','wsl.exe','conhost.exe','alacritty.exe','wezterm.exe',
    'git.exe','gitkraken.exe','fork.exe','sourcetreeapp.exe',
    'insomnia.exe','postman.exe','tableplus.exe','dbeaver.exe',
    'chrome.exe','firefox.exe','msedge.exe','brave.exe','opera.exe',
  ]),
  learning: new Set([
    'chrome.exe','firefox.exe','msedge.exe','brave.exe',
    'acrord32.exe','acrobat.exe','sumatrapdf.exe','foxitpdfeditor.exe',
    'notion.exe','obsidian.exe','onenote.exe','joplin.exe','logseq.exe',
    'kindle.exe','winword.exe','powerpnt.exe','vlc.exe','mpc-hc64.exe','mpv.exe',
    'code.exe','pycharm64.exe',
  ]),
  research: new Set([
    'chrome.exe','firefox.exe','msedge.exe','brave.exe','opera.exe',
    'acrord32.exe','acrobat.exe','sumatrapdf.exe','foxitpdfeditor.exe',
    'zotero.exe','jabref.exe','obsidian.exe','notion.exe','onenote.exe',
    'winword.exe','excel.exe','rstudio.exe','spss.exe','stata.exe','code.exe',
  ]),
  assignment: new Set([
    'winword.exe','libreoffice.exe','soffice.exe','wordpad.exe',
    'excel.exe','powerpnt.exe','acrord32.exe','acrobat.exe','sumatrapdf.exe',
    'chrome.exe','firefox.exe','msedge.exe','brave.exe',
    'obsidian.exe','notion.exe','onenote.exe',
  ]),
  creative: new Set([
    'photoshop.exe','illustrator.exe','xd.exe','figma.exe','sketch.exe',
    'inkscape.exe','gimp-2.10.exe','krita.exe','affdesigner.exe',
    'premierepro.exe','afterfx.exe','resolve.exe','kdenlive.exe','shotcut.exe',
    'fl64.exe','audacity.exe','reaper64.exe','blender.exe','maya.exe',
    '3dsmax.exe','scrivener.exe','winword.exe','code.exe',
  ]),
  video: new Set([
    'vlc.exe','mpc-hc64.exe','mpv.exe','windowsmediaplayer.exe',
    'chrome.exe','firefox.exe','msedge.exe','brave.exe',
  ]),
};

async function ensureAppRules(sessionType) {
  if (!sessionType) return {};
  if (sessionType in appRules) return appRules[sessionType] || {};
  try {
    const data = await api(`/api/activity/rules?session_type=${encodeURIComponent(sessionType)}`);
    const weights = {};
    for (const item of data.productive_apps || []) {
      weights[String(item.app_name).toLowerCase()] = Number(item.weight) || 0;
    }
    appRules[sessionType] = weights;
  } catch {
    // Leave the rules unloaded so the next poll retries; scoring falls back to
    // the built-in app lists without pretending to know exact weights.
    appRules[sessionType] = null;
  }
  return appRules[sessionType] || {};
}

async function intervalsWithCategories(rawIntervals, sessionType) {
  await ensureAppRules(sessionType);
  return (rawIntervals || []).map(iv => {
    const { category, weight } = classifyAppClient(iv.app_name, sessionType);
    return { ...iv, category, weight };
  });
}

function classifyAppClient(appName, sessionType) {
  const key = appName.toLowerCase().trim();
  if (CLIENT_NEUTRAL.has(key)) return { category: 'neutral', weight: 0 };
  if (CLIENT_ALWAYS_DISTRACTION.has(key)) return { category: 'distraction', weight: 0 };
  const weights = appRules[sessionType];
  if (weights && key in weights) return { category: 'productive', weight: weights[key] };
  const fallbackSet = CLIENT_PRODUCTIVE[sessionType];
  if (!weights && fallbackSet && fallbackSet.has(key)) return { category: 'productive', weight: 1 };
  return { category: 'distraction', weight: 0 };
}

function estimateLiveScore(intervals) {
  let productiveWeighted = 0;
  let productiveSecs = 0;
  let distractionSecs = 0;
  for (const iv of intervals) {
    const secs = iv.elapsed_seconds || 0;
    if (iv.category === 'productive') {
      productiveWeighted += secs * (iv.weight ?? 1);
      productiveSecs += secs;
    } else if (iv.category === 'distraction') {
      distractionSecs += secs;
    }
  }
  const scorable = productiveSecs + distractionSecs;
  const score = scorable > 0 ? Math.round(productiveWeighted / scorable * 100) : 0;
  const label = score >= 90 ? 'Deep Work' : score >= 75 ? 'Focused'
    : score >= 55 ? 'Moderate' : score >= 35 ? 'Distracted' : 'Off Task';
  return { score: Math.max(0, Math.min(100, score)), label };
}

/* ─── Final score and saved app activity reports ────────────────────────── */

function renderReportStatus(message) {
  const element = document.getElementById('activityReportStatus');
  if (element) element.textContent = message || '';
}

async function fetchFinalWorkScore(recordingId, sessionType) {
  if (!recordingId) return;
  clearInterval(activityPollTick);
  activityPollTick = null;
  try {
    // The authenticated backend enriches the local intervals, so the card and
    // the Excel workbook use the same per-app durations and weights.
    const params = new URLSearchParams({
      session_type: sessionType || currentSession?.type || 'coding',
      companion_token: companionPairingCode,
    });
    const data = await api(`/api/activity/reports/${encodeURIComponent(recordingId)}?${params}`);
    renderAppTimeline(data.apps || [], null);
    renderWorkScore({
      score: data.score,
      label: data.label,
      coin_multiplier: data.coin_multiplier,
      productive_seconds: data.productive_seconds,
      distraction_seconds: data.distraction_seconds,
      neutral_seconds: data.neutral_seconds,
      app_breakdown: data.apps || [],
    });
    document.getElementById('liveCurrentAppBanner')?.classList.add('hidden');
    renderReportStatus(`Recording ${recordingId} · ${formatDuration(data.total_seconds || 0)} of app time across ${(data.apps || []).length} app(s).`);
  } catch (error) {
    // The local report is still downloadable when the summary cannot load.
    renderReportStatus(`App activity was recorded locally, but its summary could not be loaded: ${errorMessage(error)}`);
  }
}

function renderActivityReports() {
  const list = document.getElementById('activityReportList');
  const empty = document.getElementById('activityReportsEmpty');
  if (!list) return;
  list.replaceChildren();
  if (!activityReports.length) {
    empty?.classList.remove('hidden');
    if (empty) empty.textContent = 'No app activity reports were saved on this device yet.';
    return;
  }
  empty?.classList.add('hidden');
  for (const report of activityReports) {
    const row = document.createElement('div');
    row.className = 'activity-report-row';
    const started = document.createElement('time');
    started.className = 'activity-report-row__time';
    started.textContent = String(report.started_at || '').replace('T', ' ').slice(0, 16);
    const meta = document.createElement('span');
    meta.className = 'activity-report-row__meta';
    const state = report.status === 'recording' ? 'recording now' : String(report.status || '').replaceAll('_', ' ');
    meta.textContent = `${report.session_type || 'session'} · ${state} · ${formatDuration(report.foreground_seconds || 0)} of app time`;
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'btn btn--ghost';
    view.textContent = 'View app time';
    view.disabled = report.status === 'recording';
    view.title = report.status === 'recording'
      ? 'Stop the recording to review its final app time.'
      : 'Show how long each app was foreground';
    view.addEventListener('click', () => { void openActivityReport(report); });
    const download = document.createElement('button');
    download.type = 'button';
    download.className = 'btn btn--ghost';
    download.textContent = 'Excel';
    download.disabled = report.status === 'recording';
    download.title = report.status === 'recording'
      ? 'Stop the recording before downloading its app activity Excel.'
      : 'Download this app activity Excel';
    download.addEventListener('click', () => { void downloadAppActivityReport(report.id); });
    row.append(started, meta, view, download);
    list.appendChild(row);
  }
}

async function loadActivityReports({ reveal = false, silent = false } = {}) {
  if (reveal) document.getElementById('activityPanel')?.classList.remove('hidden');
  if (!companionConnected || !companionPairingCode) {
    if (!silent) renderReportStatus('Connect the Windows companion to list the app activity saved on this device.');
    return;
  }
  try {
    const response = await companionFetch('/api/recordings');
    const data = await response.json();
    activityReports = Array.isArray(data.recordings) ? data.recordings : [];
    renderActivityReports();
    if (!silent) {
      renderReportStatus(`${activityReports.length} saved report${activityReports.length === 1 ? '' : 's'} on this device.`);
    }
  } catch (error) {
    if (silent) return;
    if (reveal) document.getElementById('activityPanel')?.classList.remove('hidden');
    renderReportStatus(errorMessage(error, 'Could not load the saved app activity reports.'));
  }
}

async function openActivityReport(report) {
  if (!report?.id) return;
  renderReportStatus(`Loading app time for ${report.id}…`);
  try {
    const params = new URLSearchParams({
      session_type: report.session_type || currentSession?.type || 'coding',
      companion_token: companionPairingCode,
    });
    const data = await api(`/api/activity/reports/${encodeURIComponent(report.id)}?${params}`);
    renderAppTimeline(data.apps || [], null);
    renderWorkScore({
      score: data.score,
      label: data.label,
      coin_multiplier: data.coin_multiplier,
      productive_seconds: data.productive_seconds,
      distraction_seconds: data.distraction_seconds,
      neutral_seconds: data.neutral_seconds,
      app_breakdown: data.apps || [],
    });
    document.getElementById('liveCurrentAppBanner')?.classList.add('hidden');
    renderReportStatus(`Recording ${report.id} · ${formatDuration(data.total_seconds || 0)} of app time across ${(data.apps || []).length} app(s).`);
    document.getElementById('appTimelineChart')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch (error) {
    renderReportStatus(errorMessage(error, 'Could not load this app activity report.'));
  }
}

window.loadActivityReports = loadActivityReports;
window.openActivityReport = openActivityReport;

/* ─── Attach to session lifecycle ───────────────────────────────────────── */

// Start polling when companion tracking begins
const _origStartCompanionRecording = typeof startCompanionRecording === 'function'
  ? startCompanionRecording : null;

function startLiveActivityPolling(recordingId) {
  clearInterval(activityPollTick);
  activityPollTick = null;
  if (!recordingId || !companionPairingCode) return;
  document.getElementById('activityPanel')?.classList.remove('hidden');
  document.getElementById('workScorePanel')?.classList.add('hidden');
  document.getElementById('appTimelineChart').innerHTML =
    '<p class="timeline-empty">Starting app activity tracking…</p>';
  // Poll every 5 seconds for live updates
  activityPollTick = setInterval(pollLiveTimeline, 5000);
  pollLiveTimeline(); // immediate first poll
}

// Stop polling and show final score when recording ends
function stopLiveActivityPolling(recordingId, sessionType) {
  clearInterval(activityPollTick);
  activityPollTick = null;
  if (recordingId && sessionType) {
    fetchFinalWorkScore(recordingId, sessionType);
  }
}

// Expose so existing recording start/stop hooks can call them
window.startLiveActivityPolling = startLiveActivityPolling;
window.stopLiveActivityPolling = stopLiveActivityPolling;

/* ─── Wire companion start/stop buttons ─────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Augment the recording start button
  const startBtn = document.getElementById('recordingStartBtn');
  if (startBtn) {
    startBtn.addEventListener('click', () => {
      // After a short delay, check if companion tracking started
      setTimeout(() => {
        if (companionTrackingId) startLiveActivityPolling(companionTrackingId);
      }, 1500);
    });
  }

  // Augment the recording stop button
  const stopBtn = document.getElementById('recordingStopBtn');
  if (stopBtn) {
    stopBtn.addEventListener('click', () => {
      const id = companionTrackingId;
      const type = currentSession?.type || 'coding';
      setTimeout(() => stopLiveActivityPolling(id, type), 2000);
    });
  }
});

/* ═══════════════════════════════════════════════════════════════════════════
   FOCUS STUDIO — goal ring, streaks, insights, milestones, quick start
═══════════════════════════════════════════════════════════════════════════ */

let lastDashboard = null;
let lastSessions = [];
let lastAnalytics = null;

const GOAL_RING_CIRCUMFERENCE = 2 * Math.PI * 52;

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function renderGoal(summary) {
  const goal = summary?.goal || {};
  const streak = summary?.streak || {};
  const minutes = Math.round(Number(goal.today_focus_seconds || 0) / 60);
  const target = Number(goal.daily_goal_minutes || 0);
  const percent = target ? Math.max(0, Math.min(100, Number(goal.percent || 0))) : 0;
  const ring = document.getElementById('goalRing');
  if (ring) ring.style.strokeDashoffset = String(GOAL_RING_CIRCUMFERENCE * (1 - percent / 100));
  setText('goalPercent', target ? `${Math.round(percent)}%` : '—');
  setText('goalMinutes', target
    ? `${minutes} of ${target} min today`
    : `${minutes} min today · no goal set`);
  const input = document.getElementById('goalInput');
  if (input && document.activeElement !== input) input.value = target ? String(target) : '';
  setText('goalStreak', String(streak.current ?? 0));
  setText('goalStreakNote', `Longest: ${streak.longest ?? 0} ${Number(streak.longest) === 1 ? 'day' : 'days'}`);
}

function setGoalMessage(message, isError = false) {
  const node = document.getElementById('goalMessage');
  if (!node) return;
  node.textContent = message || '';
  node.style.color = isError ? 'var(--danger)' : '';
}

async function saveGoal(event) {
  event.preventDefault();
  const input = document.getElementById('goalInput');
  if (!input) return;
  const value = Math.round(Number(input.value || 0));
  if (!Number.isFinite(value) || value < 0 || value > 720) {
    setGoalMessage('Use a goal between 0 and 720 minutes.', true);
    return;
  }
  try {
    await api('/api/goals', { method: 'PUT', body: JSON.stringify({ daily_goal_minutes: value }) });
    setGoalMessage(value ? 'Daily goal saved.' : 'Goal cleared.');
    await loadDashboardData();
  } catch (error) {
    setGoalMessage(errorMessage(error, 'Could not save your goal.'), true);
  }
}

function renderQuickStart(sessions) {
  const repeat = document.getElementById('repeatLastBtn');
  if (!repeat) return;
  const last = sessions?.[0];
  repeat.disabled = !last;
  repeat.title = last
    ? `Repeat “${last.title}” · ${(SESSION_TYPES[last.type] || SESSION_TYPES.coding).label}${last.duration_minutes ? ` · ${last.duration_minutes}m` : ''}`
    : 'Finish a session once to repeat it here';
}

function repeatLastSession() {
  const last = lastSessions?.[0];
  if (!last) return;
  openModal({
    type: last.type,
    task: last.task_description || '',
    goal: last.goal || '',
    duration: last.duration_minutes || 25,
  });
}

function insightItem(label, value, note) {
  const item = document.createElement('li');
  item.className = 'insight-item';
  if (value === '—') item.classList.add('insight-item--empty');
  const labelNode = document.createElement('span');
  labelNode.className = 'insight-item__label';
  labelNode.textContent = label;
  const valueNode = document.createElement('strong');
  valueNode.className = 'insight-item__value';
  valueNode.textContent = value;
  const noteNode = document.createElement('small');
  noteNode.className = 'insight-item__note';
  noteNode.textContent = note;
  item.append(labelNode, valueNode, noteNode);
  return item;
}

function renderInsights(analytics, dashboard) {
  const list = document.getElementById('insightList');
  if (!list) return;
  const summary = analytics?.summary || {};
  const buckets = analytics?.buckets || [];
  const bestDay = buckets.reduce(
    (best, bucket) => (bucket.focus_seconds > (best?.focus_seconds || 0) ? bucket : best), null);
  const hours = analytics?.hour_of_day || [];
  const bestHour = hours.reduce(
    (best, hour) => (hour.focus_seconds > (best?.focus_seconds || 0) ? hour : best), null);
  const comparison = analytics?.comparison || {};
  const streak = analytics?.streak || dashboard?.streak || {};
  const delta = comparison.delta_percent;
  list.replaceChildren(
    insightItem(
      'Best day',
      bestDay && bestDay.focus_seconds ? formatDuration(bestDay.focus_seconds) : '—',
      bestDay && bestDay.focus_seconds ? bestDay.detail : 'No completed work session in this period'),
    insightItem(
      'Best start hour',
      bestHour && bestHour.focus_seconds ? `${String(bestHour.hour).padStart(2, '0')}:00` : '—',
      bestHour && bestHour.focus_seconds
        ? `${formatDuration(bestHour.focus_seconds)} began in this hour`
        : 'Your first session reveals this'),
    insightItem(
      'Typical block',
      summary.median_focus_session_minutes != null ? `${summary.median_focus_session_minutes}m` : '—',
      'Median completed work session'),
    insightItem(
      'vs previous period',
      delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta}%`,
      comparison.previous_focus_seconds
        ? `${formatDuration(comparison.previous_focus_seconds)} in the previous period`
        : 'No earlier period to compare'),
    insightItem(
      'Coins this period',
      String(analytics?.coins_earned ?? 0),
      'From completed timer categories'),
    insightItem(
      'Longest streak',
      `${streak.longest ?? 0}d`,
      `Current streak ${streak.current ?? 0} ${Number(streak.current) === 1 ? 'day' : 'days'}`),
  );
}

const ACHIEVEMENTS = [
  { icon: '✦', title: 'First block', detail: 'Finish one tracked session', earned: context => context.sessions >= 1 },
  { icon: '⧉', title: 'Ten blocks', detail: 'Finish ten tracked sessions', earned: context => context.sessions >= 10 },
  { icon: '◷', title: 'One hour', detail: 'Track 60 focus minutes', earned: context => context.seconds >= 3600 },
  { icon: '◈', title: 'Ten hours', detail: 'Track ten focus hours', earned: context => context.seconds >= 36000 },
  { icon: '❖', title: 'Fifty blocks', detail: 'Finish fifty tracked sessions', earned: context => context.sessions >= 50 },
  { icon: '▲', title: 'Three-day streak', detail: 'Work three days in a row', earned: context => context.longestStreak >= 3 },
  { icon: '◆', title: 'Seven-day streak', detail: 'Work seven days in a row', earned: context => context.longestStreak >= 7 },
  { icon: '◎', title: 'Goal reached', detail: "Reach today's focus goal", earned: context => context.goalMet },
];

function renderAchievements(summary) {
  const grid = document.getElementById('achievementGrid');
  if (!grid) return;
  const totals = summary?.totals || {};
  const streak = summary?.streak || {};
  const context = {
    sessions: Number(totals.completed_sessions || 0),
    seconds: Number(totals.focus_seconds || 0),
    longestStreak: Number(streak.longest || 0),
    goalMet: Boolean(summary?.goal?.met),
  };
  grid.replaceChildren(...ACHIEVEMENTS.map(badge => {
    const earned = badge.earned(context);
    const card = document.createElement('article');
    card.className = `badge-card${earned ? ' badge-card--earned' : ''}`;
    card.setAttribute('aria-label', `${badge.title}: ${earned ? 'earned' : 'locked'}`);
    const icon = document.createElement('span');
    icon.className = 'badge-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = badge.icon;
    const body = document.createElement('div');
    body.className = 'badge-body';
    const title = document.createElement('p');
    title.className = 'badge-title';
    title.textContent = badge.title;
    const detail = document.createElement('p');
    detail.className = 'badge-detail';
    detail.textContent = badge.detail;
    const state = document.createElement('span');
    state.className = 'badge-state';
    state.textContent = earned ? 'Earned' : 'Locked';
    body.append(title, detail, state);
    card.append(icon, body);
    return card;
  }));
}

/* ═══════════════════════════════════════════════════════════════════════════
   NATIVE CHARTS — dependency-free SVG, drawn from the analytics API
═══════════════════════════════════════════════════════════════════════════ */

const SVG_NS = 'http://www.w3.org/2000/svg';

function chartColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#8a8a8a';
}

function chartPalette() {
  return [
    chartColor('--accent'), chartColor('--sage'), chartColor('--gold'),
    chartColor('--break'), chartColor('--ink-2'), chartColor('--muted'),
  ];
}

function svgNode(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function chartHost(id) {
  return document.getElementById(id);
}

function showChartEmpty(host, message) {
  if (!host) return;
  const note = document.createElement('p');
  note.className = 'chart-empty';
  note.textContent = message;
  host.replaceChildren(note);
}

function svgLabel(x, y, text, anchor = 'middle') {
  const node = svgNode('text', { x, y, class: 'chart-axis-text', 'text-anchor': anchor });
  node.textContent = text;
  return node;
}

function chartSvg(width, height, label) {
  return svgNode('svg', {
    viewBox: `0 0 ${width} ${height}`,
    class: 'chart-svg',
    role: 'img',
    'aria-label': label,
  });
}

/**
 * Chart view boxes use one user unit per CSS pixel so labels stay readable.
 * The host width is measured at draw time and charts are redrawn on resize.
 */
function chartWidth(host, fallback, minimum) {
  const measured = Math.round(host?.clientWidth || 0);
  return Math.max(minimum, measured || fallback);
}

function scheduleChartRerender() {
  if (scheduleChartRerender.timer) clearTimeout(scheduleChartRerender.timer);
  scheduleChartRerender.timer = setTimeout(() => {
    if (lastAnalytics) renderNativeCharts(lastAnalytics);
  }, 220);
}

function niceMax(value) {
  if (!Number.isFinite(value) || value <= 0) return 10;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const scaled = value / magnitude;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * magnitude;
}

function renderTrendChart(buckets) {
  const host = chartHost('chartTrend');
  if (!host) return;
  const points = (buckets || []).map(bucket => ({
    label: bucket.label,
    detail: bucket.detail,
    value: Math.round((Number(bucket.focus_seconds) || 0) / 60),
  }));
  if (!points.length || !points.some(point => point.value > 0)) {
    showChartEmpty(host, 'No completed focus blocks in this period yet.');
    return;
  }
  const width = chartWidth(host, 660, 320);
  const height = 220;
  const pad = { left: 36, right: 14, top: 16, bottom: 28 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(...points.map(point => point.value)));
  const x = index => (points.length === 1
    ? pad.left + plotW / 2
    : pad.left + (index / (points.length - 1)) * plotW);
  const y = value => pad.top + plotH - (value / max) * plotH;
  const svg = chartSvg(width, height, 'Focus minutes across the selected period');
  for (let tick = 0; tick <= 2; tick += 1) {
    const value = (max / 2) * tick;
    const lineY = y(value);
    svg.appendChild(svgNode('line', {
      x1: pad.left, x2: width - pad.right, y1: lineY, y2: lineY, class: 'chart-gridline',
    }));
    svg.appendChild(svgLabel(pad.left - 7, lineY + 3, String(Math.round(value)), 'end'));
  }
  const linePath = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`)
    .join(' ');
  const baseline = pad.top + plotH;
  const areaPath = `${linePath} L${x(points.length - 1).toFixed(1)},${baseline} L${x(0).toFixed(1)},${baseline} Z`;
  svg.appendChild(svgNode('path', { d: areaPath, class: 'chart-area' }));
  svg.appendChild(svgNode('path', { d: linePath, class: 'chart-line' }));
  const labelEvery = Math.ceil(points.length / 7);
  points.forEach((point, index) => {
    const dot = svgNode('circle', { cx: x(index), cy: y(point.value), r: 3.2, class: 'chart-dot' });
    const title = svgNode('title');
    title.textContent = `${point.detail || point.label}: ${point.value} min`;
    dot.appendChild(title);
    svg.appendChild(dot);
    if (index % labelEvery === 0 || index === points.length - 1) {
      svg.appendChild(svgLabel(x(index), height - 8, point.label));
    }
  });
  host.replaceChildren(svg);
}

function renderBarChart(id, entries, options = {}) {
  const host = chartHost(id);
  if (!host) return;
  const {
    empty = 'No data yet.', colors = null, labelEvery = 1, valueSuffix = '',
  } = options;
  const data = (entries || []).map(entry => ({
    label: String(entry.label),
    value: Number(entry.value) || 0,
    title: entry.title || '',
    color: entry.color || null,
    className: entry.className || 'chart-bar',
  }));
  if (!data.length || !data.some(entry => entry.value > 0)) {
    showChartEmpty(host, empty);
    return;
  }
  const width = chartWidth(host, 480, 260);
  const height = 200;
  const pad = { left: 34, right: 10, top: 20, bottom: 28 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(...data.map(entry => entry.value)));
  const slot = plotW / data.length;
  const barW = Math.max(4, Math.min(38, slot * 0.64));
  const svg = chartSvg(width, height, options.label || 'Bar chart');
  for (let tick = 0; tick <= 2; tick += 1) {
    const lineY = pad.top + plotH - (tick / 2) * plotH;
    svg.appendChild(svgNode('line', {
      x1: pad.left, x2: width - pad.right, y1: lineY, y2: lineY, class: 'chart-gridline',
    }));
    svg.appendChild(svgLabel(pad.left - 6, lineY + 3, String(Math.round((max / 2) * tick)), 'end'));
  }
  data.forEach((entry, index) => {
    const barH = (entry.value / max) * plotH;
    const barX = pad.left + slot * index + (slot - barW) / 2;
    const bar = svgNode('rect', {
      x: barX.toFixed(1), y: (pad.top + plotH - barH).toFixed(1),
      width: barW.toFixed(1), height: Math.max(0, barH).toFixed(1),
      class: entry.className, rx: 1,
    });
    if (entry.color) bar.style.fill = entry.color;
    else if (colors) bar.style.fill = colors[index % colors.length];
    const title = svgNode('title');
    title.textContent = `${entry.title || entry.label}: ${entry.value}${valueSuffix}`;
    bar.appendChild(title);
    svg.appendChild(bar);
    if (data.length <= 8 && entry.value > 0) {
      svg.appendChild(svgLabel(
        barX + barW / 2,
        Math.max(10, pad.top + plotH - barH - 5),
        String(Math.round(entry.value)),
      ));
    }
    if (index % labelEvery === 0) {
      svg.appendChild(svgLabel(barX + barW / 2, height - 8, entry.label));
    }
  });
  host.replaceChildren(svg);
}

function renderDonutChart(id, entries, options = {}) {
  const host = chartHost(id);
  if (!host) return;
  const data = (entries || []).filter(entry => Number(entry.value) > 0);
  if (!data.length) {
    showChartEmpty(host, options.empty || 'No data to chart yet.');
    return;
  }
  const total = data.reduce((sum, entry) => sum + Number(entry.value), 0);
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const size = 148;
  const center = size / 2;
  const svg = chartSvg(size, size, options.label || 'Share chart');
  svg.style.maxWidth = '170px';
  svg.appendChild(svgNode('circle', {
    cx: center, cy: center, r: radius,
    fill: 'none', stroke: chartColor('--line'), 'stroke-width': 15,
  }));
  let offset = 0;
  data.forEach((entry, index) => {
    const length = (Number(entry.value) / total) * circumference;
    const arc = Math.max(0, length - 2.5);
    const color = entry.color || chartPalette()[index % chartPalette().length];
    const circle = svgNode('circle', {
      cx: center, cy: center, r: radius,
      fill: 'none', stroke: color, 'stroke-width': 15,
      'stroke-dasharray': `${arc} ${circumference - arc}`,
      'stroke-dashoffset': -offset,
      transform: `rotate(-90 ${center} ${center})`,
    });
    const title = svgNode('title');
    title.textContent = `${entry.label}: ${entry.title || entry.value}`;
    circle.appendChild(title);
    svg.appendChild(circle);
    offset += length;
  });
  const centerValue = svgNode('text', {
    x: center, y: center + 2, 'text-anchor': 'middle', class: 'chart-donut__total',
  });
  centerValue.textContent = options.centerValue || String(Math.round(total));
  const centerLabel = svgNode('text', {
    x: center, y: center + 17, 'text-anchor': 'middle', class: 'chart-donut__caption',
  });
  centerLabel.textContent = options.centerLabel || '';
  svg.append(centerValue, centerLabel);

  const legend = document.createElement('div');
  legend.className = 'chart-legend';
  data.forEach((entry, index) => {
    const color = entry.color || chartPalette()[index % chartPalette().length];
    const item = document.createElement('div');
    item.className = 'chart-legend__item';
    const dot = document.createElement('span');
    dot.className = 'chart-legend__dot';
    dot.style.background = color;
    const label = document.createElement('span');
    label.className = 'chart-legend__label';
    label.textContent = entry.label;
    const value = document.createElement('span');
    value.className = 'chart-legend__value';
    value.textContent = `${Math.round((Number(entry.value) / total) * 100)}%`;
    item.append(dot, label, value);
    legend.appendChild(item);
  });
  host.replaceChildren(svg, legend);
}

const TYPE_LABELS = {
  coding: 'Coding', learning: 'Learning', research: 'Research',
  assignment: 'Assignment', creative: 'Creative', video: 'Learning video', break: 'Break',
};

function renderNativeCharts(analytics) {
  if (!analytics) return;
  const palette = chartPalette();
  renderTrendChart(analytics.buckets);

  const typeEntries = Object.entries(analytics.summary?.focus_type_seconds || {})
    .filter(([, seconds]) => Number(seconds) > 0)
    .map(([key, seconds], index) => ({
      label: TYPE_LABELS[key] || key.replaceAll('_', ' '),
      value: Number(seconds),
      color: palette[index % palette.length],
      title: formatDuration(seconds),
    }));
  renderDonutChart('chartTypeDonut', typeEntries, {
    centerValue: formatDuration(analytics.summary?.focus_seconds || 0),
    centerLabel: 'focus',
    label: 'Focus time share by session type',
    empty: 'No focus time in this period yet.',
  });

  renderBarChart('chartDurationHistogram', (analytics.session_length_distribution || []).map(item => ({
    label: item.label, value: item.focus_sessions, title: formatDuration(item.focus_seconds),
  })), {
    empty: 'No completed work blocks yet.',
    label: 'Sessions by work block length',
    colors: [chartColor('--sage')],
    valueSuffix: ' sessions',
  });

  renderBarChart('chartHourBars', (analytics.hour_of_day || []).map(item => ({
    label: String(item.hour).padStart(2, '0'),
    value: Math.round((Number(item.focus_seconds) || 0) / 60),
    title: `${String(item.hour).padStart(2, '0')}:00 · ${item.focus_sessions} session(s)`,
  })), {
    empty: 'No sessions in this period.',
    label: 'Focus minutes by session start hour',
    labelEvery: 3,
    colors: [chartColor('--gold')],
    valueSuffix: ' min',
  });

  renderBarChart('chartWeekdayBars', (analytics.weekday_pattern || []).map(item => ({
    label: item.label,
    value: Math.round((Number(item.focus_seconds) || 0) / 60),
    title: `${item.focus_sessions} session(s)`,
  })), {
    empty: 'No sessions in this period.',
    label: 'Focus minutes by weekday',
    colors: [chartColor('--rating')],
    valueSuffix: ' min',
  });

  renderBarChart('chartRating', (analytics.rating_distribution || []).map(item => ({
    label: String(item.rating), value: item.samples, title: `Rating ${item.rating} of 5`,
  })), {
    empty: 'Add an optional 1–5 self-rating when you end a session.',
    label: 'Self-rated focus distribution',
    colors: [chartColor('--gold')],
    valueSuffix: ' ratings',
  });

  const comparison = analytics.comparison || {};
  renderBarChart('chartComparison', [
    {
      label: 'Previous',
      value: Math.round((Number(comparison.previous_focus_seconds) || 0) / 60),
      title: comparison.previous_start_date
        ? `${comparison.previous_start_date} to ${comparison.previous_end_date}`
        : 'Previous period',
      className: 'chart-bar',
    },
    {
      label: 'This period',
      value: Math.round((Number(analytics.summary?.focus_seconds) || 0) / 60),
      title: `${analytics.start_date} to ${analytics.end_date}`,
      className: 'chart-bar--accent',
    },
  ], {
    empty: 'No focus minutes to compare yet.',
    label: 'Focus minutes compared with the previous period',
    colors: null,
    valueSuffix: ' min',
  });
}

function renderAppDonut(apps) {
  const host = chartHost('appUsageDonut');
  if (!host) return;
  const palette = chartPalette();
  const totals = new Map();
  for (const app of apps || []) {
    const name = app.app_name || 'Unknown app';
    const seconds = Number(app.elapsed_seconds) || 0;
    if (seconds <= 0) continue;
    totals.set(name, (totals.get(name) || 0) + seconds);
  }
  const sorted = [...totals.entries()].sort((left, right) => right[1] - left[1]);
  if (!sorted.length) {
    showChartEmpty(host, 'No app activity to chart yet.');
    return;
  }
  const top = sorted.slice(0, 5);
  const rest = sorted.slice(5).reduce((sum, [, seconds]) => sum + seconds, 0);
  const entries = top.map(([name, seconds], index) => ({
    label: name, value: seconds, color: palette[index % palette.length], title: formatDuration(seconds),
  }));
  if (rest > 0) {
    entries.push({ label: 'Other apps', value: rest, color: chartColor('--muted'), title: formatDuration(rest) });
  }
  const totalSeconds = sorted.reduce((sum, [, seconds]) => sum + seconds, 0);
  renderDonutChart('appUsageDonut', entries, {
    centerValue: formatDuration(totalSeconds),
    centerLabel: 'app time',
    label: 'Share of foreground app time',
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   KEYBOARD SHORTCUTS
═══════════════════════════════════════════════════════════════════════════ */

function isTypingTarget(target) {
  if (!target || typeof target.closest !== 'function') return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function openShortcuts() {
  const overlay = document.getElementById('shortcutOverlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  document.getElementById('shortcutCloseBtn')?.focus();
}

function closeShortcuts() {
  document.getElementById('shortcutOverlay')?.classList.add('hidden');
}

function installKeyboardShortcuts() {
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented) return;
    if (event.key === 'Escape') {
      closeShortcuts();
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (isTypingTarget(event.target) || event.target?.closest?.('button, a, [role="button"]')) return;

    if (event.key === '?') {
      event.preventDefault();
      openShortcuts();
      return;
    }
    if (event.key.toLowerCase() === 'n') {
      const overlay = document.getElementById('modalOverlay');
      if (!overlay || overlay.classList.contains('hidden')) {
        event.preventDefault();
        openModal();
      }
      return;
    }
    if (event.code === 'Space' && currentSession && ['running', 'paused'].includes(currentSession.status)) {
      event.preventDefault();
      transitionSession(currentSession.status === 'running' ? 'pause' : 'resume');
    }
  });
}

