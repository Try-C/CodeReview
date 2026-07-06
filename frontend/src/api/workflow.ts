import { authHeaders, getJson, requestJson } from '@/api/client'
import type {
  ProjectFileSelection,
  ReviewMode,
  ReviewTask,
  TokenResponse,
  UploadCompleteResponse,
  UploadSession,
} from '@/types/workflow'

const API_PREFIX = '/api/v1'
const UPLOAD_BATCH_SIZE = 20

export async function register(
  username: string,
  password: string,
): Promise<void> {
  await requestJson(`${API_PREFIX}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  const { data } = await requestJson<TokenResponse>(
    `${API_PREFIX}/auth/login`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    },
  )
  return data
}

export async function initializeUpload(
  projectName: string,
  files: ProjectFileSelection[],
): Promise<UploadSession> {
  const { data } = await requestJson<UploadSession>(
    `${API_PREFIX}/uploads/init`,
    {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        project_name: projectName,
        files: files.map(({ file, relativePath }) => ({
          relative_path: relativePath,
          size: file.size,
        })),
      }),
    },
  )
  return data
}

export async function uploadAcceptedFiles(
  session: UploadSession,
  files: ProjectFileSelection[],
  onProgress?: (uploaded: number, total: number) => void,
): Promise<UploadSession> {
  const pendingPaths = new Set(
    session.manifest
      .filter((item) => item.status === 'pending')
      .map((item) => item.relative_path),
  )
  const accepted = files.filter((item) => pendingPaths.has(item.relativePath))
  let current = session

  for (let offset = 0; offset < accepted.length; offset += UPLOAD_BATCH_SIZE) {
    const batch = accepted.slice(offset, offset + UPLOAD_BATCH_SIZE)
    const body = new FormData()
    for (const item of batch) {
      body.append('files', item.file, item.relativePath)
    }
    const result = await requestJson<UploadSession>(
      `${API_PREFIX}/uploads/${session.upload_id}/files`,
      {
        method: 'POST',
        headers: authHeaders(),
        body,
      },
    )
    current = result.data
    onProgress?.(
      Math.min(offset + batch.length, accepted.length),
      accepted.length,
    )
  }

  return current
}

export async function completeUpload(
  uploadId: string,
): Promise<UploadCompleteResponse> {
  const { data } = await requestJson<UploadCompleteResponse>(
    `${API_PREFIX}/uploads/${uploadId}/complete`,
    {
      method: 'POST',
      headers: authHeaders(),
    },
  )
  return data
}

export async function createReview(
  projectId: number,
  reviewMode: ReviewMode,
): Promise<ReviewTask> {
  const { data } = await requestJson<ReviewTask>(
    `${API_PREFIX}/projects/${projectId}/reviews`,
    {
      method: 'POST',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        idempotency_key: crypto.randomUUID(),
        review_mode: reviewMode,
      }),
    },
  )
  return data
}

export async function fetchReview(taskId: number): Promise<ReviewTask> {
  const { data } = await getJson<ReviewTask>(
    `${API_PREFIX}/reviews/${taskId}`,
    {
      headers: authHeaders(),
    },
  )
  return data
}

export async function cancelReview(taskId: number): Promise<ReviewTask> {
  const { data } = await requestJson<ReviewTask>(
    `${API_PREFIX}/reviews/${taskId}/cancel`,
    {
      method: 'POST',
      headers: authHeaders(),
    },
  )
  return data
}
