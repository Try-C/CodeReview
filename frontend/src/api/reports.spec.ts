import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchReportMarkdown, submitFeedback } from '@/api/reports'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('report API', () => {
  it('sends authentication and JSON feedback to the versioned endpoint', async () => {
    localStorage.setItem('access_token', 'test-token')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 3, status: 'confirmed' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await submitFeedback(3, 'confirmed')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(init.method).toBe('PATCH')
    expect(headers.get('Authorization')).toBe('Bearer test-token')
    expect(init.body).toBe(JSON.stringify({ status: 'confirmed' }))
  })

  it('downloads the markdown response as text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('# Report', {
          status: 200,
          headers: { 'Content-Type': 'text/markdown' },
        }),
      ),
    )

    await expect(fetchReportMarkdown(9)).resolves.toBe('# Report')
  })
})
