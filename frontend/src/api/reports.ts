/** Report API client per spec §16. */

import { getJson, getText, requestJson } from './client'
import type { IssueDetail, ReportAPIResponse } from '@/types/report'

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchReport(taskId: number): Promise<ReportAPIResponse> {
  const { data } = await getJson<ReportAPIResponse>(
    `/api/v1/reviews/${taskId}/report`,
    { headers: authHeaders() },
  )
  return data
}

export async function fetchIssues(taskId: number): Promise<IssueDetail[]> {
  const { data } = await getJson<IssueDetail[]>(
    `/api/v1/reviews/${taskId}/issues`,
    { headers: authHeaders() },
  )
  return data
}

export async function fetchIssue(issueId: number): Promise<IssueDetail> {
  const { data } = await getJson<IssueDetail>(`/api/v1/issues/${issueId}`, {
    headers: authHeaders(),
  })
  return data
}

export async function submitFeedback(
  issueId: number,
  status: string,
): Promise<{ id: number; status: string }> {
  const { data } = await requestJson<{ id: number; status: string }>(
    `/api/v1/issues/${issueId}/feedback`,
    {
      method: 'PATCH',
      headers: {
        ...authHeaders(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status }),
    },
  )
  return data
}

export async function fetchReportMarkdown(taskId: number): Promise<string> {
  const { data } = await getText(
    `/api/v1/reviews/${taskId}/export?format=markdown`,
    { headers: authHeaders() },
  )
  return data
}
