import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, getJson } from '@/api/client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getJson', () => {
  it('returns typed data and the server request ID', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ready' }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': 'server-request-1',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await getJson<{ status: string }>('/api/v1/health/ready', {
      headers: { 'X-Request-ID': 'client-request-1' },
    })

    expect(result).toEqual({
      data: { status: 'ready' },
      requestId: 'server-request-1',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/health/ready',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('throws the backend error contract without losing its request ID', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: 'SERVICE_UNAVAILABLE',
            message: 'Backend is starting',
            request_id: 'server-request-2',
            details: { retryable: true },
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    const error = await getJson('/api/v1/health/ready').catch(
      (reason: unknown) => reason,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 503,
      code: 'SERVICE_UNAVAILABLE',
      requestId: 'server-request-2',
      details: { retryable: true },
    })
  })
})
