// Type declarations for i18n module
import type { SupportedLocale } from './types'

export interface I18n {
  t: (key: string, params?: Record<string, string | number>) => string
  tBatch: (keys: string[], params?: Record<string, string | number>) => Record<string, string>
  tWithDefault: (key: string, defaultValue: string, params?: Record<string, string | number>) => string
  setLocale: (locale: SupportedLocale) => boolean
  getLocale: () => SupportedLocale
  initLocale: () => SupportedLocale
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
  formatDate: (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => string
  formatRelativeTime: (date: Date | string | number) => string
  useI18n: () => {
    locale: import('vue').ComputedRef<SupportedLocale>
    t: (key: string, params?: Record<string, string | number>) => string
    tBatch: (keys: string[], params?: Record<string, string | number>) => Record<string, string>
    tWithDefault: (key: string, defaultValue: string, params?: Record<string, string | number>) => string
    setLocale: (locale: SupportedLocale) => boolean
    getLocale: () => SupportedLocale
    formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
    formatDate: (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => string
    formatRelativeTime: (date: Date | string | number) => string
    SUPPORTED_LOCALES: Record<SupportedLocale, string>
    onLocaleChange: (callback: (locale: SupportedLocale) => void) => () => void
  }
  SUPPORTED_LOCALES: Record<SupportedLocale, string>
  DEFAULT_LOCALE: SupportedLocale
}

export declare const t: (key: string, params?: Record<string, string | number>) => string
export declare const tBatch: (keys: string[], params?: Record<string, string | number>) => Record<string, string>
export declare const tWithDefault: (key: string, defaultValue: string, params?: Record<string, string | number>) => string
export declare const setLocale: (locale: SupportedLocale) => boolean
export declare const getLocale: () => SupportedLocale
export declare const initLocale: () => SupportedLocale
export declare const formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
export declare const formatDate: (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => string
export declare const formatRelativeTime: (date: Date | string | number) => string
export declare const useI18n: () => {
  locale: import('vue').ComputedRef<SupportedLocale>
  t: (key: string, params?: Record<string, string | number>) => string
  tBatch: (keys: string[], params?: Record<string, string | number>) => Record<string, string>
  tWithDefault: (key: string, defaultValue: string, params?: Record<string, string | number>) => string
  setLocale: (locale: SupportedLocale) => boolean
  getLocale: () => SupportedLocale
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
  formatDate: (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => string
  formatRelativeTime: (date: Date | string | number) => string
  SUPPORTED_LOCALES: Record<SupportedLocale, string>
  onLocaleChange: (callback: (locale: SupportedLocale) => void) => () => void
}
export declare const SUPPORTED_LOCALES: Record<SupportedLocale, string>
export declare const DEFAULT_LOCALE: SupportedLocale
export default I18n
