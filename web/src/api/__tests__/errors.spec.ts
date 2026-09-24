import { describe, it, expect, beforeEach } from 'vitest'
import { normalizeApiError } from '../index'
import { setLocale, initLocale } from '../../i18n'

describe('API error normalization (S3-5)', () => {
  beforeEach(() => {
    initLocale()
  })

  it('maps HTTP status to a unified error code and localized message', () => {
    setLocale('zh-CN')
    const axiosError = {
      response: { status: 404, data: {} },
      config: {},
      isAxiosError: true,
    }
    const result = normalizeApiError(axiosError)
    expect(result.status).toBe(404)
    expect(result.code).toBe('not_found')
    expect(result.message).toBe('请求的资源不存在')
  })

  it('prefers the backend detail string when present', () => {
    setLocale('en-US')
    const axiosError = {
      response: { status: 400, data: { detail: 'book name too long' } },
      config: {},
    }
    const result = normalizeApiError(axiosError)
    expect(result.code).toBe('bad_request')
    expect(result.message).toBe('book name too long')
  })

  it('maps network failures without a response to network_error', () => {
    const networkError = { request: {}, message: 'Network Error', config: {} }
    const result = normalizeApiError(networkError)
    expect(result.status).toBeNull()
    expect(result.code).toBe('network_error')
  })

  it('maps aborted requests to timeout', () => {
    const timeoutError = { code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded', config: {} }
    const result = normalizeApiError(timeoutError)
    expect(result.code).toBe('timeout')
  })
})
