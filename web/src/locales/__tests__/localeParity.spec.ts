/**
 * Audit item 9 — i18n completeness + component-library rigidity regression guards.
 *
 * 1. en-US and zh-CN locale packs MUST keep exact key parity. The English pack
 *    is a mirror of zh-CN; any drift (a key present in one but not the other)
 *    either breaks a UI string or silently falls back to Chinese. This test pins
 *    that the two packs have identical flat key sets.
 *
 * 2. Every `@/` import specifier used in `.vue`/`.ts` source MUST resolve to a
 *    real file under `web/src`. This guards against re-introducing fictional
 *    components (e.g. a non-existent `@/components/ui/*` library) that would
 *    crash the build. The `@/` alias maps to `web/src` (see vite/vitest config).
 */

import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import enUS from '../../locales/en-US.js'
import zhCN from '../../locales/zh-CN.js'

const SRC_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

/** Flatten a nested locale object into dotted leaf keys. */
function flattenKeys(obj: unknown, prefix = ''): string[] {
  const out: string[] = []
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const key of Object.keys(obj)) {
      const next = prefix ? `${prefix}.${key}` : key
      out.push(...flattenKeys((obj as Record<string, unknown>)[key], next))
    }
  } else if (prefix) {
    out.push(prefix)
  }
  return out
}

describe('locale key parity (en-US <-> zh-CN)', () => {
  it('has identical flat key sets across both language packs', () => {
    const enKeys = new Set(flattenKeys(enUS))
    const zhKeys = new Set(flattenKeys(zhCN))

    const onlyEn = [...enKeys].filter((k) => !zhKeys.has(k)).sort()
    const onlyZh = [...zhKeys].filter((k) => !enKeys.has(k)).sort()

    expect(onlyEn, `keys only in en-US: ${onlyEn.join(', ')}`).toEqual([])
    expect(onlyZh, `keys only in zh-CN: ${onlyZh.join(', ')}`).toEqual([])
    expect(enKeys.size).toBeGreaterThan(0)
    expect(enKeys.size).toBe(zhKeys.size)
  })
})

/** Resolve a `@/x` specifier to an existing file/dir under SRC_ROOT, else null. */
function resolveAlias(spec: string): string | null {
  if (!spec.startsWith('@/')) return null
  const target = path.resolve(SRC_ROOT, spec.slice(2))
  const extensions = ['.ts', '.tsx', '.vue', '.js', '.jsx', '.json', '.d.ts']
  const candidates: string[] = [target, ...extensions.map((e) => target + e)]
  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c
  }
  // directory with an index entry
  for (const e of extensions) {
    const idx = path.join(target, `index${e}`)
    if (fs.existsSync(idx) && fs.statSync(idx).isFile()) return idx
  }
  return null
}

describe('no fictional @/ component imports', () => {
  it('resolves every @/ import specifier in source to a real file', () => {
    const specifiers = new Set<string>()
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (['node_modules', 'dist', 'coverage'].includes(entry.name)) continue
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
        } else if (/\.(vue|ts|tsx|js|jsx)$/.test(entry.name)) {
          // Only production source imports matter; skip the test files themselves
          // (their comments contain example specifiers like '@/x').
          if (/\.(spec|test)\.(ts|tsx|js|jsx)$/.test(entry.name)) continue
          const content = fs.readFileSync(full, 'utf8')
          // Only treat real import contexts as import specifiers:
          //   import X from '@/...'
          //   import '@/...'
          //   import('@/...')
          const importRe =
            /\bimport\b(?:[^;'"]*?from\s*)?\s*['"]\s*(@\/[a-zA-Z0-9_./-]+)\s*['"]|\bimport\s*\(\s*['"]\s*(@\/[a-zA-Z0-9_./-]+)\s*['"]\s*\)/g
          let m: RegExpExecArray | null
          while ((m = importRe.exec(content)) !== null) {
            const spec = m[1] || m[2]
            if (spec) specifiers.add(spec)
          }
        }
      }
    }
    walk(SRC_ROOT)

    expect(specifiers.size, 'expected at least some @/ imports').toBeGreaterThan(0)

    const unresolved: string[] = []
    for (const spec of [...specifiers].sort()) {
      if (resolveAlias(spec) === null) unresolved.push(spec)
    }
    expect(unresolved, `unresolved @/ imports: ${unresolved.join(', ')}`).toEqual([])
  })
})
