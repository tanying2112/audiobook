/**
 * Audiobook Studio - i18n 核心模块
 * 
 * 国际化工具，支持多语言切换、嵌套键访问、参数插值
 * 版本: v1.0
 * 日期: 2026-06-27
 */

import zhCN from './locales/zh-CN.js'

// 支持的语言列表
export const SUPPORTED_LOCALES = {
  'zh-CN': '简体中文',
  // 'en-US': 'English (US)',
  // 'ja-JP': '日本語',
  // 'ko-KR': '한국어',
  // 'fr-FR': 'Français',
  // 'de-DE': 'Deutsch',
  // 'es-ES': 'Español',
}

// 默认语言
export const DEFAULT_LOCALE = 'zh-CN'

// 语言包存储
const messages = {
  'zh-CN': zhCN,
}

// 当前语言
let currentLocale = DEFAULT_LOCALE

// 获取当前语言
export function getLocale() {
  return currentLocale
}

// 设置当前语言
export function setLocale(locale) {
  if (SUPPORTED_LOCALES[locale]) {
    currentLocale = locale
    // 持久化到 localStorage
    localStorage.setItem('app-locale', locale)
    return true
  }
  return false
}

// 初始化语言（从 localStorage 或浏览器语言检测）
export function initLocale() {
  const saved = localStorage.getItem('app-locale')
  if (saved && SUPPORTED_LOCALES[saved]) {
    currentLocale = saved
  } else {
    // 检测浏览器语言
    const browserLang = navigator.language || navigator.userLanguage
    if (SUPPORTED_LOCALES[browserLang]) {
      currentLocale = browserLang
    } else if (SUPPORTED_LOCALES[browserLang.split('-')[0]]) {
      currentLocale = browserLang.split('-')[0]
    }
  }
  return currentLocale
}

// 嵌套键访问：'common.loading' -> messages['zh-CN'].common.loading
function getNestedValue(obj, path) {
  return path.split('.').reduce((current, key) => current?.[key], obj)
}

// 翻译函数
export function t(key, params = {}) {
  const localeMessages = messages[currentLocale] || messages[DEFAULT_LOCALE]
  let translation = getNestedValue(localeMessages, key)
  
  // 如果找不到翻译，返回 key 本身
  if (translation === undefined || translation === null) {
    console.warn(`[i18n] Translation not found for key: ${key} (locale: ${currentLocale})`)
    return key
  }
  
  // 参数插值：{count} -> params.count
  if (typeof translation === 'string' && Object.keys(params).length > 0) {
    return translation.replace(/\{(\w+)\}/g, (match, paramKey) => {
      return params[paramKey] !== undefined ? params[paramKey] : match
    })
  }
  
  return translation
}

// 获取完整的语言包对象（用于批量访问）
export function getMessages(locale = currentLocale) {
  return messages[locale] || messages[DEFAULT_LOCALE]
}

// 添加新语言包
export function addLocale(locale, messageObject) {
  messages[locale] = messageObject
}

// 批量翻译工具
export function tBatch(keys, params = {}) {
  const result = {}
  for (const key of keys) {
    result[key] = t(key, params)
  }
  return result
}

// 带默认值的翻译
export function tWithDefault(key, defaultValue, params = {}) {
  const translation = t(key, params)
  return translation === key ? defaultValue : translation
}

// 格式化数字（根据语言环境）
export function formatNumber(value, options = {}) {
  return new Intl.NumberFormat(currentLocale, options).format(value)
}

// 格式化日期（根据语言环境）
export function formatDate(date, options = {}) {
  return new Intl.DateTimeFormat(currentLocale, options).format(new Date(date))
}

// 格式化相对时间
export function formatRelativeTime(date) {
  const now = Date.now()
  const diff = now - new Date(date).getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  const weeks = Math.floor(days / 7)
  const months = Math.floor(days / 30)
  const years = Math.floor(days / 365)
  
  if (seconds < 60) return t('datetime.seconds_ago', { count: seconds })
  if (minutes < 60) return t('datetime.minutes_ago', { count: minutes })
  if (hours < 24) return t('datetime.hours_ago', { count: hours })
  if (days < 7) return t('datetime.days_ago', { count: days })
  if (weeks < 4) return t('datetime.weeks_ago', { count: weeks })
  if (months < 12) return t('datetime.months_ago', { count: months })
  return t('datetime.years_ago', { count: years })
}

// Vue 组合式 API 集成
import { ref, computed, watchEffect } from 'vue'

// 响应式当前语言
const localeRef = ref(currentLocale)

// 语言变更监听器
const localeChangeListeners = new Set()

export function useI18n() {
  // 监听语言变更
  watchEffect(() => {
    localeRef.value = currentLocale
    localeChangeListeners.forEach(listener => listener(currentLocale))
  })
  
  return {
    locale: computed(() => localeRef.value),
    t,
    tBatch,
    tWithDefault,
    setLocale,
    getLocale,
    formatNumber,
    formatDate,
    formatRelativeTime,
    SUPPORTED_LOCALES,
    onLocaleChange: (callback) => {
      localeChangeListeners.add(callback)
      return () => localeChangeListeners.delete(callback)
    },
  }
}

// 初始化
initLocale()

export default {
  t,
  tBatch,
  tWithDefault,
  setLocale,
  getLocale,
  initLocale,
  formatNumber,
  formatDate,
  formatRelativeTime,
  useI18n,
  SUPPORTED_LOCALES,
  DEFAULT_LOCALE,
}
