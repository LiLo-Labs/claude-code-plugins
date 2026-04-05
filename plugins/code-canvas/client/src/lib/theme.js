const STORAGE_KEY = 'code-canvas-theme';

export function getInitialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {}
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem(STORAGE_KEY, theme); } catch {}
}

export function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  setTheme(next);
  return next;
}
