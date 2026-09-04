import { ref, readonly } from 'vue'

const THEME_KEY = 'app-theme'

export type ThemeMode = 'light' | 'dark' | 'auto'

/** 当前模式（响应式） */
export const themeMode = ref<ThemeMode>('auto')

/** 解析后的实际深色状态 */
export const isDark = ref(false)

/** 监听系统偏好变化 */
let mediaQuery: MediaQueryList | null = null

function applyTheme(dark: boolean) {
  isDark.value = dark
  const html = document.documentElement
  if (dark) {
    html.classList.add('dark')
  } else {
    html.classList.remove('dark')
  }
}

function computeDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true
  if (mode === 'light') return false
  // auto
  return mediaQuery?.matches ?? false
}

export function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
  localStorage.setItem(THEME_KEY, mode)
  applyTheme(computeDark(mode))
}

/** 初始化：读取持久化、监听系统偏好 */
export function initTheme() {
  if (typeof window === 'undefined') return
  // 读取持久化
  const saved = localStorage.getItem(THEME_KEY) as ThemeMode | null
  if (saved) {
    themeMode.value = saved
  }
  // 监听系统深色偏好
  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = (e: MediaQueryListEvent) => {
    if (themeMode.value === 'auto') {
      applyTheme(e.matches)
    }
  }
  mediaQuery.addEventListener?.('change', handler)
  // 初始应用
  applyTheme(computeDark(themeMode.value))
  // 清理函数（可选，页面卸载时）
  // window.addEventListener('beforeunload', () => mediaQuery?.removeEventListener('change', handler))
}

/** 切换：循环 auto -> dark -> light */
export function cycleTheme() {
  const modes: ThemeMode[] = ['auto', 'dark', 'light']
  const idx = modes.indexOf(themeMode.value)
  const next = modes[(idx + 1) % modes.length]
  setThemeMode(next)
}

/** 获取当前模式的中文标签（供 UI 用） */
export function getThemeLabel(mode: ThemeMode, t: (key: string) => string): string {
  const map: Record<ThemeMode, string> = {
    auto: t('settings.theme_options.auto'),
    dark: t('settings.theme_options.dark'),
    light: t('settings.theme_options.light'),
  }
  return map[mode] || mode
}

/** 响应式导出（供模板直接用） */
export const useTheme = () => ({
  themeMode: readonly(themeMode),
  isDark: readonly(isDark),
  setThemeMode,
  cycleTheme,
  getThemeLabel,
})