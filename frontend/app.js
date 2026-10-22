/**
 * FocusForge AI — app.js
 * Phase 1 scaffold: UI wiring, sample data, session timer prototype.
 *
 * NOT implemented in Phase 1:
 *  - Persistent session storage
 *  - Backend writes (analytics, XP, skills)
 *  - Screen recording
 *  - Authentication
 *  - AI coach
 */

'use strict';

/* ════════════════════════════════════════════════════════════
   SAMPLE DATA  (replaced by real API responses in Phase 2+)
════════════════════════════════════════════════════════════ */
const SAMPLE_STATS = {
  productiveTime:  '3h 42m',
  focusSessions:   '5 sessions',
  skillProgress:   'Python +8 pts',
  xpLevel:         '350 XP · Lv 1',
};

const SAMPLE_SKILLS = [
  { name: 'Python',            icon: '🐍', pct: 62, color: '#a78bfa' },
  { name: 'FastAPI / Backend', icon: '⚡', pct: 38, color: '#22d3ee' },
  { name: 'Data Analysis',     icon: '📊', pct: 45, color: '#34d399' },
  { name: 'JavaScript',        icon: '🟨', pct: 55, color: '#fbbf24' },
  { name: 'Machine Learning',  icon: '🤖', pct: 20, color: '#f87171' },
];

const SAMPLE_ACHIEVEMENTS = [
  { icon: '🔥', name: 'First Spark',    desc: 'Complete your first session',    xp: '+50 XP',  unlocked: true  },
  { icon: '⏰', name: 'Early Bird',     desc: 'Start a session before 8 AM',    xp: '+75 XP',  unlocked: false },
  { icon: '📚', name: 'Deep Learner',   desc: 'Study for 2 hours straight',     xp: '+100 XP', unlocked: false },
  { icon: '🎯', name: 'Laser Focus',    desc: 'Complete 5 sessions in a day',   xp: '+150 XP', unlocked: false },
  { icon: '🏆', name: 'Week Warrior',   desc: '7 consecutive active days',      xp: '+300 XP', unlocked: false },
  { icon: '🚀', name: 'Level Up!',      desc: 'Reach Level 2',                  xp: '+200 XP', unlocked: false },
];

/* ════════════════════════════════════════════════════════════
   DOM HELPERS
════════════════════════════════════════════════════════════ */
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

/* ════════════════════════════════════════════════════════════
   BACKEND HEALTH CHECK
════════════════════════════════════════════════════════════ */
const HEALTH_URL = '/api/health';

async function checkBackendHealth() {
  const dot  = $('#statusDot');
  const text = $('#statusText');

  dot.className  = 'status-dot status-dot--checking';
  text.textContent = 'Checking…';

  try {
    const res  = await fetch(HEALTH_URL, { cache: 'no-store' });
    const data = await res.json();

    if (res.ok && data.status === 'ok') {
      dot.className    = 'status-dot status-dot--ok';
      text.textContent = 'Backend OK';
    } else {
      throw new Error(`Unexpected status: ${res.status}`);
    }
  } catch {
    dot.className    = 'status-dot status-dot--error';
    text.textContent = 'Backend offline';
  }
}

/* ════════════════════════════════════════════════════════════
   SAMPLE STATS RENDERER
════════════════════════════════════════════════════════════ */
function renderStats() {
  const ids = {
    productiveTime:  'productiveTime',
    focusSessions:   'focusSessions',
    skillProgress:   'skillProgress',
    xpLevel:         'xpLevel',
  };
  Object.entries(ids).forEach(([key, id]) => {
    const el = $(`#${id}`);
    if (el) el.textContent = SAMPLE_STATS[key];
  });
}

/* ════════════════════════════════════════════════════════════
   SKILLS RENDERER
════════════════════════════════════════════════════════════ */
function renderSkills() {
  const container = $('#skillsList');
  if (!container) return;

  container.innerHTML = SAMPLE_SKILLS.map(s => `
    <div class="skill-item">
      <span class="skill-icon" aria-hidden="true">${s.icon}</span>
      <div class="skill-info">
        <span class="skill-name">${s.name}</span>
        <div class="skill-bar-track" role="progressbar"
             aria-valuenow="${s.pct}" aria-valuemin="0" aria-valuemax="100"
             aria-label="${s.name} skill progress: ${s.pct}%">
          <div class="skill-bar-fill"
               style="width:0%; background: linear-gradient(90deg, ${s.color}88, ${s.color});"
               data-target="${s.pct}">
          </div>
        </div>
      </div>
      <span class="skill-pct">${s.pct}%</span>
    </div>
  `).join('');

  // Animate bars on next frame
  requestAnimationFrame(() => {
    $$('.skill-bar-fill').forEach(bar => {
      bar.style.width = bar.dataset.target + '%';
    });
  });
}

/* ════════════════════════════════════════════════════════════
   ACHIEVEMENTS RENDERER
════════════════════════════════════════════════════════════ */
function renderAchievements() {
  const container = $('#achievementsGrid');
  if (!container) return;

  container.innerHTML = SAMPLE_ACHIEVEMENTS.map(a => `
    <div class="achievement-card ${a.unlocked ? '' : 'achievement-card--locked'}"
         title="${a.unlocked ? 'Unlocked' : 'Locked — not yet earned'}">
      <div class="achievement-icon" aria-hidden="true">${a.icon}</div>
      <div class="achievement-name">${a.name}</div>
      <div class="achievement-desc">${a.desc}</div>
      <div class="achievement-xp">${a.xp}</div>
    </div>
  `).join('');
}

/* ════════════════════════════════════════════════════════════
   SESSION TIMER (UI prototype — no persistence)
════════════════════════════════════════════════════════════ */
let timerInterval   = null;
let sessionSeconds  = 0;
let sessionPaused   = false;
let sessionRunning  = false;

function formatTime(secs) {
  const h = String(Math.floor(secs / 3600)).padStart(2, '0');
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function startTimer(type = 'Deep Work') {
  if (sessionRunning) return;

  sessionRunning = true;
  sessionPaused  = false;
  sessionSeconds = 0;

  const idle   = $('#sessionIdle');
  const active = $('#sessionActive');
  const tag    = $('#sessionTag');
  const display = $('#timerDisplay');

  idle.classList.add('hidden');
  active.classList.remove('hidden');
  tag.textContent = type;
  display.textContent = formatTime(0);

  timerInterval = setInterval(() => {
    if (!sessionPaused) {
      sessionSeconds++;
      display.textContent = formatTime(sessionSeconds);
    }
  }, 1000);
}

function pauseTimer() {
  sessionPaused = !sessionPaused;
  const pauseBtn = $('#pauseBtn');
  if (pauseBtn) pauseBtn.textContent = sessionPaused ? '▶ Resume' : '⏸ Pause';
}

function stopTimer() {
  clearInterval(timerInterval);
  timerInterval  = null;
  sessionRunning = false;
  sessionPaused  = false;
  sessionSeconds = 0;

  const idle   = $('#sessionIdle');
  const active = $('#sessionActive');
  const display = $('#timerDisplay');

  idle.classList.remove('hidden');
  active.classList.add('hidden');
  display.textContent = '00:00:00';

  const pauseBtn = $('#pauseBtn');
  if (pauseBtn) pauseBtn.textContent = '⏸ Pause';
}

/* ════════════════════════════════════════════════════════════
   SESSION START MODAL
════════════════════════════════════════════════════════════ */
function openModal() {
  const overlay = $('#modalOverlay');
  if (overlay) overlay.classList.remove('hidden');
}

function closeModal() {
  const overlay = $('#modalOverlay');
  if (overlay) overlay.classList.add('hidden');
}

function handleModalStart() {
  const typeEl = $('#sessionType');
  const type   = typeEl ? typeEl.options[typeEl.selectedIndex].text : 'Deep Work';
  closeModal();
  startTimer(type);
}

/* ════════════════════════════════════════════════════════════
   SIDEBAR NAVIGATION
════════════════════════════════════════════════════════════ */
function wireNavigation() {
  $$('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      $$('.nav-item').forEach(n => {
        n.classList.remove('nav-item--active');
        n.removeAttribute('aria-current');
      });
      item.classList.add('nav-item--active');
      item.setAttribute('aria-current', 'page');

      // Close sidebar on mobile after navigation
      if (window.innerWidth <= 768) closeSidebar();
    });
  });
}

/* ════════════════════════════════════════════════════════════
   MOBILE SIDEBAR TOGGLE
════════════════════════════════════════════════════════════ */
function openSidebar() {
  const sidebar = $('#sidebar');
  const toggle  = $('#sidebarToggle');
  if (sidebar) sidebar.classList.add('is-open');
  if (toggle)  toggle.setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
  const sidebar = $('#sidebar');
  const toggle  = $('#sidebarToggle');
  if (sidebar) sidebar.classList.remove('is-open');
  if (toggle)  toggle.setAttribute('aria-expanded', 'false');
}

/* ════════════════════════════════════════════════════════════
   LIVE CLOCK (topbar date)
════════════════════════════════════════════════════════════ */
function updateClock() {
  const el = $('.page-subtitle');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  });
}

/* ════════════════════════════════════════════════════════════
   BOOTSTRAP
════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {

  // Render sample data
  renderStats();
  renderSkills();
  renderAchievements();

  // Backend health (best effort; fails gracefully if not running)
  checkBackendHealth();

  // Refresh health every 30 s
  setInterval(checkBackendHealth, 30_000);

  // Update date
  updateClock();

  // Wire event listeners
  wireNavigation();

  // Start session buttons (both topbar and hero)
  $$('#startSessionBtn, #startSessionBtn2').forEach(btn =>
    btn.addEventListener('click', openModal)
  );

  // Pause / stop buttons
  const pauseBtn = $('#pauseBtn');
  const stopBtn  = $('#stopBtn');
  if (pauseBtn) pauseBtn.addEventListener('click', pauseTimer);
  if (stopBtn)  stopBtn.addEventListener('click', stopTimer);

  // Modal controls
  const cancelBtn = $('#modalCancelBtn');
  const startBtn  = $('#modalStartBtn');
  const overlay   = $('#modalOverlay');

  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
  if (startBtn)  startBtn.addEventListener('click', handleModalStart);
  if (overlay) {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeModal();
    });
  }

  // ESC closes modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  // Mobile sidebar toggle
  const toggle = $('#sidebarToggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      const sidebar = $('#sidebar');
      const isOpen  = sidebar && sidebar.classList.contains('is-open');
      isOpen ? closeSidebar() : openSidebar();
    });
  }

  // Click outside sidebar on mobile to close
  document.addEventListener('click', e => {
    if (window.innerWidth > 768) return;
    const sidebar = $('#sidebar');
    const toggleEl = $('#sidebarToggle');
    if (sidebar && !sidebar.contains(e.target) && e.target !== toggleEl && !toggleEl?.contains(e.target)) {
      closeSidebar();
    }
  });
});
