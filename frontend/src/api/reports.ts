/** Report API client per spec §16. */

import { client } from './client'
import type { IssueDetail, ReportAPIResponse } from '@/types/report'

export async function fetchReport(taskId: number): Promise<ReportAPIResponse> {
  const { data } = await client.get<ReportAPIResponse>(`/reviews/${taskId}/report`)
  return data
}

export async function fetchIssues(taskId: number): Promise<IssueDetail[]> {
  const { data } = await client.get<IssueDetail[]>(`/reviews/${taskId}/issues`)
  return data
}

export async function fetchIssue(issueId: number): Promise<IssueDetail> {
  const { data } = await client.get<IssueDetail>(`/issues/${issueId}`)
  return data
}

export async function submitFeedback(
  issueId: number,
  status: string,
): Promise<{ id: number; status: string }> {
  const { data } = await client.patch<{ id: number; status: string }>(
    `/issues/${issueId}/feedback`,
    { status },
  )
  return data
}

export async function fetchReportMarkdown(taskId: number): Promise<string> {
  const { data } = await client.get<string>(`/reviews/${taskId}/export?format=markdown`)
  return data
}
