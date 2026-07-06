import type { ApiErrorResponse, ApiResult } from '@/types/api'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? ''
const apiBaseUrl = configuredBaseUrl.replace(/\/+$/, '')

/** Shared auth header factory — used by all API modules. */
export function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Check whether the stored token has expired. */
export function isTokenExpired(): boolean {
  const expiresAt = localStorage.getItem('access_token_expires_at')
  if (!expiresAt) return false
  return Date.now() > Number(expiresAt)
}

/** Clear all auth state and redirect to login. */
export function clearAuth(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('access_token_expires_at')
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string
  readonly details: Record<string, unknown>

  constructor(status: number, payload: ApiErrorResponse) {
    super(payload.message)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.requestId = payload.request_id
    this.details = payload.details
  }
}

function createRequestId(): string {
  return crypto.randomUUID()
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  const callerRequestId = headers.get('X-Request-ID') ?? createRequestId()
  headers.set('X-Request-ID', callerRequestId)

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    method: init.method ?? 'GET',
    headers,
  })
  const requestId = response.headers.get('X-Request-ID') ?? callerRequestId
  const payload: unknown = await response.json()

  if (!response.ok) {
    const errorPayload = payload as Partial<ApiErrorResponse>
    throw new ApiError(response.status, {
      code: errorPayload.code ?? 'HTTP_ERROR',
      message: errorPayload.message ?? 'Request failed',
      request_id: errorPayload.request_id ?? requestId,
      details: errorPayload.details ?? {},
    })
  }

  return {
    data: payload as T,
    requestId,
  }
}

export function getJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  return requestJson<T>(path, { ...init, method: 'GET' })
}

export function postJson<T>(
  path: string,
  body: unknown,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  return requestJson<T>(path, {
    ...init,
    method: 'POST',
    headers: {
      ...init.headers,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
}

export function patchJson<T>(
  path: string,
  body: unknown,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  return requestJson<T>(path, {
    ...init,
    method: 'PATCH',
    headers: {
      ...init.headers,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
}

export async function getText(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<string>> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'text/markdown')

  const callerRequestId = headers.get('X-Request-ID') ?? createRequestId()
  headers.set('X-Request-ID', callerRequestId)

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    method: 'GET',
    headers,
  })
  const requestId = response.headers.get('X-Request-ID') ?? callerRequestId

  if (!response.ok) {
    const payload = (await response.json()) as Partial<ApiErrorResponse>
    throw new ApiError(response.status, {
      code: payload.code ?? 'HTTP_ERROR',
      message: payload.message ?? 'Request failed',
      request_id: payload.request_id ?? requestId,
      details: payload.details ?? {},
    })
  }

  return {
    data: await response.text(),
    requestId,
  }
}
