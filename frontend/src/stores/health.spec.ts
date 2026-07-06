import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { fetchReadiness } from '@/api/health'
import { useHealthStore } from '@/stores/health'

vi.mock('@/api/health', () => ({
  fetchReadiness: vi.fn(),
}))

describe('health store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stores a successful readiness response', async () => {
    vi.mocked(fetchReadiness).mockResolvedValue({
      data: {
        status: 'ready',
        service: 'CodeReview Agent',
        version: '0.1.0',
        checks: { configuration: 'ok' },
      },
      requestId: 'request-success',
    })
    const store = useHealthStore()

    await store.refresh()

    expect(store.phase).toBe('ready')
    expect(store.isReady).toBe(true)
    expect(store.readiness?.checks.configuration).toBe('ok')
    expect(store.requestId).toBe('request-success')
    expect(store.lastCheckedAt).toBeInstanceOf(Date)
  })

  it('keeps the structured API error available to the page', async () => {
    vi.mocked(fetchReadiness).mockRejectedValue(
      new ApiError(503, {
        code: 'SERVICE_UNAVAILABLE',
        message: 'Backend is starting',
        request_id: 'request-error',
        details: {},
      }),
    )
    const store = useHealthStore()

    await store.refresh()

    expect(store.phase).toBe('error')
    expect(store.isReady).toBe(false)
    expect(store.readiness).toBeNull()
    expect(store.requestId).toBe('request-error')
    expect(store.errorMessage).toBe('SERVICE_UNAVAILABLE: Backend is starting')
  })
})
