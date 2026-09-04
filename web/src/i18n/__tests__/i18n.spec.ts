import { describe, it, expect, beforeEach } from 'vitest'
import {
  t,
  setLocale,
  getLocale,
  initLocale,
  SUPPORTED_LOCALES,
  DEFAULT_LOCALE,
} from '../../i18n'
import enUS from '../../locales/en-US.js'

const LS_KEY = 'app-locale'

describe('i18n (M-03 multi-language support)', () => {
  beforeEach(() => {
    localStorage.removeItem(LS_KEY)
    initLocale()
  })

  it('enables English (en-US) as a supported locale', () => {
    expect(Object.keys(SUPPORTED_LOCALES)).toContain('en-US')
    expect(SUPPORTED_LOCALES['en-US']).toBe('English (US)')
  })

  it('uses zh-CN as the default locale', () => {
    expect(DEFAULT_LOCALE).toBe('zh-CN')
  })

  it('translates known keys for en-US', () => {
    setLocale('en-US')
    expect(getLocale()).toBe('en-US')
    expect(t('auth.login')).toBe('Log in')
    expect(t('nav.projects')).toBe('Projects')
    expect(t('publish.title')).toBe('Publish')
  })

  it('translates known keys for zh-CN (default)', () => {
    setLocale('zh-CN')
    expect(t('auth.login')).toBe('登录')
    expect(t('nav.projects')).toBe('项目列表')
  })

  it('substitutes params in en-US strings', () => {
    setLocale('en-US')
    expect(t('upload.upload_progress', { progress: 42 })).toBe('Upload progress: 42%')
  })

  it('falls back to the default locale (zh-CN) when a key is missing in the current locale', () => {
    // Switch to a non-default locale
    setLocale('en-US')
    // Simulate a key present in zh-CN but absent from en-US. The translation
    // must fall back to the Chinese default instead of the raw key.
    const backup = enUS.common.loading
    delete enUS.common.loading
    try {
      expect(t('common.loading')).toBe('加载中...')
    } finally {
      enUS.common.loading = backup
    }
  })

  it('returns the raw key when the translation is absent in every locale', () => {
    setLocale('en-US')
    expect(t('this.key.does.not.exist')).toBe('this.key.does.not.exist')
  })

  it('rejects an unsupported locale and keeps the current one', () => {
    setLocale('zh-CN')
    const ok = setLocale('xx-XX' as never)
    expect(ok).toBe(false)
    expect(getLocale()).toBe('zh-CN')
  })

  it('accepts a supported locale and persists it to localStorage', () => {
    const ok = setLocale('en-US')
    expect(ok).toBe(true)
    expect(localStorage.getItem(LS_KEY)).toBe('en-US')
  })

  it('rehydrates the locale from localStorage on init', () => {
    localStorage.setItem(LS_KEY, 'en-US')
    const restored = initLocale()
    expect(restored).toBe('en-US')
    expect(getLocale()).toBe('en-US')
  })
})
