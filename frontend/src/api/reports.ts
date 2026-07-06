/** Report API client per spec §16. */

import { authHeaders, getJson, getText, patchJson } from './client'
import type { IssueDetail, ReportAPIResponse } from '@/types/report'

export type FeedbackStatus = 'confirmed' | 'false_positive' | 'needs_review'

export async function fetchReport(taskId: number): Promise<ReportAPIResponse> {
  const { data } = await getJson<ReportAPIResponse>(
    `/api/v1/reviews/${taskId}/report`,
    { headers: authHeaders() },
  )
  return data
}

export async function fetchIssues(
  taskId: number,
  riskFilter?: string,
  categoryFilter?: string,
  search?: string,
): Promise<IssueDetail[]> {
  const params = new URLSearchParams()
  if (riskFilter) params.set('risk_level', riskFilter)
  if (categoryFilter) params.set('category', categoryFilter)
  if (search) params.set('search', search)
  const qs = params.toString()
  const { data } = await getJson<IssueDetail[]>(
    `/api/v1/reviews/${taskId}/issues${qs ? `?${qs}` : ''}`,
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
  status: FeedbackStatus,
): Promise<{ id: number; status: string }> {
  const { data } = await patchJson<{ id: number; status: string }>(
    `/api/v1/issues/${issueId}/feedback`,
    { status },
    { headers: authHeaders() },
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
