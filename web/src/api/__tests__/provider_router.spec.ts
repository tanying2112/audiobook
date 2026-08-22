import { describe, it, expect, vi, beforeEach } from 'vitest'
import api from '../index'
import * as svc from '../provider_router'

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

// The mocked module keeps the real AxiosInstance type at compile time; cast
// to the subset of methods we use so .mockResolvedValue() type-checks.
type MockApi = {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}
const mockedApi = api as unknown as MockApi

describe('api/provider_router.ts (S2.1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getProviders hits /api/v1/providers/ and returns the list', async () => {
    mockedApi.get.mockResolvedValue({ data: { providers: [{ id: 1, name: 'p' }], total: 1 } })
    const res = await svc.getProviders()
    expect(mockedApi.get).toHaveBeenCalledWith('/api/v1/providers/')
    expect(res.providers).toHaveLength(1)
    expect(res.total).toBe(1)
  })

  it('createProvider posts to /api/v1/providers/', async () => {
    mockedApi.post.mockResolvedValue({ data: { id: 2, name: 'new' } })
    const res = await svc.createProvider({ name: 'new', provider_type: 'openai' })
    expect(mockedApi.post).toHaveBeenCalledWith('/api/v1/providers/', {
      name: 'new',
      provider_type: 'openai',
    })
    expect(res.id).toBe(2)
  })

  it('updateProvider puts to /api/v1/providers/:id', async () => {
    mockedApi.put.mockResolvedValue({ data: { id: 3, name: 'upd' } })
    await svc.updateProvider(3, { is_enabled: false })
    expect(mockedApi.put).toHaveBeenCalledWith('/api/v1/providers/3', { is_enabled: false })
  })

  it('deleteProvider deletes /api/v1/providers/:id', async () => {
    mockedApi.delete.mockResolvedValue({})
    await svc.deleteProvider(4)
    expect(mockedApi.delete).toHaveBeenCalledWith('/api/v1/providers/4')
  })

  it('getModelsByProvider hits the nested models path', async () => {
    mockedApi.get.mockResolvedValue({ data: { models: [{ id: 9, name: 'm' }], total: 1 } })
    const res = await svc.getModelsByProvider(5)
    expect(mockedApi.get).toHaveBeenCalledWith('/api/v1/providers/5/models/')
    expect(res.models[0].id).toBe(9)
  })

  it('createModel posts to the provider models path', async () => {
    mockedApi.post.mockResolvedValue({ data: { id: 11, name: 'm' } })
    await svc.createModel(5, { name: 'm' })
    expect(mockedApi.post).toHaveBeenCalledWith('/api/v1/providers/5/models/', { name: 'm' })
  })

  it('updateModel puts to /api/v1/providers/:pid/models/:mid', async () => {
    mockedApi.put.mockResolvedValue({ data: { id: 11 } })
    await svc.updateModel(5, 11, { is_enabled: true })
    expect(mockedApi.put).toHaveBeenCalledWith('/api/v1/providers/5/models/11', {
      is_enabled: true,
    })
  })

  it('deleteModel deletes the nested model path', async () => {
    mockedApi.delete.mockResolvedValue({})
    await svc.deleteModel(5, 11)
    expect(mockedApi.delete).toHaveBeenCalledWith('/api/v1/providers/5/models/11')
  })

  it('reloadProviders posts to /api/v1/providers/reload', async () => {
    mockedApi.post.mockResolvedValue({ data: { db_sync: 'ok', yaml_reload: 'ok', errors: [] } })
    const res = await svc.reloadProviders()
    expect(mockedApi.post).toHaveBeenCalledWith('/api/v1/providers/reload')
    expect(res.db_sync).toBe('ok')
  })
})
