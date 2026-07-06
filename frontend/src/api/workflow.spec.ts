import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createReview,
  initializeUpload,
  login,
  uploadAcceptedFiles,
} from '@/api/workflow'
import type { UploadSession } from '@/types/workflow'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('review workflow API', () => {
  it('logs in with JSON credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'local-token',
          token_type: 'bearer',
          expires_in: 1800,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(login('reviewer', 'secure-password')).resolves.toMatchObject({
      access_token: 'local-token',
    })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(init.body).toBe(
      JSON.stringify({ username: 'reviewer', password: 'secure-password' }),
    )
  })

  it('initializes the complete folder manifest with authentication', async () => {
    localStorage.setItem('access_token', 'local-token')
    const source = new File(['print("ok")'], 'main.py', {
      type: 'text/x-python',
    })
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          upload_id: 'upload-1',
          project_id: null,
          project_name: 'demo',
          status: 'created',
          total_files: 1,
          uploaded_files: 0,
          skipped_files: 0,
          failed_files: 0,
          manifest: [],
        }),
        {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await initializeUpload('demo', [
      { file: source, relativePath: 'src/main.py' },
    ])

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer local-token')
    expect(JSON.parse(String(init.body))).toEqual({
      project_name: 'demo',
      files: [{ relative_path: 'src/main.py', size: source.size }],
    })
  })

  it('uploads only server-accepted files and preserves relative paths', async () => {
    localStorage.setItem('access_token', 'local-token')
    const pythonFile = new File(['print("ok")'], 'main.py')
    const readme = new File(['docs'], 'README.md')
    const session: UploadSession = {
      upload_id: 'upload-1',
      project_id: null,
      project_name: 'demo',
      status: 'created',
      total_files: 2,
      uploaded_files: 0,
      skipped_files: 1,
      failed_files: 0,
      manifest: [
        {
          relative_path: 'src/main.py',
          declared_size: pythonFile.size,
          status: 'pending',
          language: 'python',
          reason: null,
        },
        {
          relative_path: 'README.md',
          declared_size: readme.size,
          status: 'skipped',
          language: null,
          reason: 'UNSUPPORTED_FILE_TYPE',
        },
      ],
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...session,
          status: 'uploading',
          uploaded_files: 1,
          skipped_files: 1,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await uploadAcceptedFiles(session, [
      { file: pythonFile, relativePath: 'src/main.py' },
      { file: readme, relativePath: 'README.md' },
    ])

    expect(fetchMock).toHaveBeenCalledOnce()
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = init.body as FormData
    const uploaded = body.getAll('files') as File[]
    expect(uploaded).toHaveLength(1)
    expect(uploaded[0]?.name).toBe('src/main.py')
  })

  it('creates a review with a unique idempotency key', async () => {
    localStorage.setItem('access_token', 'local-token')
    vi.stubGlobal('crypto', {
      ...crypto,
      randomUUID: vi.fn(() => '00000000-0000-4000-8000-000000000001'),
    })
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 7,
          project_id: 3,
          status: 'pending',
          review_mode: 'comprehensive',
          current_stage: null,
          progress: 0,
          error_code: null,
          error_message: null,
          fallback_reason: null,
        }),
        {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(createReview(3, 'comprehensive')).resolves.toMatchObject({
      id: 7,
    })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({
      idempotency_key: '00000000-0000-4000-8000-000000000001',
      review_mode: 'comprehensive',
    })
  })
})
