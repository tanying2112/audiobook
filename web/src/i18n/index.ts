// Canonical i18n entry point (audit rec #7).
//
// The implementation lives in ../i18n.js (plain JS, typed via ../i18n.d.ts).
// This barrel re-exports the same runtime bindings so that the directory import
// `@/i18n` / `./i18n` and the legacy `./i18n.js` reference resolve to the SAME
// module instance — there is exactly one i18n store, one init, one locale state.
//
// Named re-exports (not `export *`) keep this valid under verbatimModuleSyntax.
export {
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
} from '../i18n.js'
