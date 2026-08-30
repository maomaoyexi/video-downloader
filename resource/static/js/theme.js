/**
 * 主题管理器 — 明 / 暗两态
 *
 * 偏好保存到 localStorage，未设置时跟随系统。
 * 深色只是覆盖 :root 里的颜色变量（dark.css），组件样式不变。
 */

const THEME_KEY = 'video-dl-theme';

/** 获取系统级主题偏好。 */
function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** 获取 localStorage 中存储的主题设置。 */
function getStoredTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch(e) { return null; }
}

/**
 * 应用主题。
 * @param {string} theme - light / dark。
 * @param {boolean} animate - 是否播放颜色过渡。
 * @param {boolean} persist - 是否保存为用户偏好。
 */
function applyTheme(theme, animate = false, persist = true) {
  const html = document.documentElement;
  if(animate) {
    html.classList.add('theme-transitioning');
    void html.offsetWidth;
  }
  html.setAttribute('data-theme', theme);
  if(persist) {
    try { localStorage.setItem(THEME_KEY, theme); } catch(e) {}
  }
  if(animate) {
    clearTimeout(html._themeTimeout);
    html._themeTimeout = setTimeout(() => html.classList.remove('theme-transitioning'), 420);
  }
}

/** 切换深色 / 浅色主题，并恢复重构前的旋转反馈。 */
function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  applyTheme(next, true, true);
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.classList.remove('spin');
    void btn.offsetWidth;
    btn.classList.add('spin');
    setTimeout(() => btn.classList.remove('spin'), 430);
  });
}

/** 初始化主题系统：应用存储/系统偏好，监听系统主题变更。 */
function initTheme() {
  const stored = getStoredTheme();
  applyTheme(stored || getSystemTheme(), false, Boolean(stored));

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
    if (!getStoredTheme()) applyTheme(e.matches ? 'light' : 'dark', true, false);
  });

  document.querySelectorAll('.theme-toggle').forEach(btn => btn.addEventListener('click', toggleTheme));
}
