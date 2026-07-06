/** Report and issue types per spec §17.2 */

export interface SeverityStats {
  high: number
  medium: number
  low: number
  total: number
}

export interface MetricsSummary {
  llm_call_count: number
  input_tokens: number
  output_tokens: number
  estimated_cost: string | null
  cost_status: string
  cost_display: string
  elapsed_seconds: number | null
}

export interface ReportData {
  task_id: number
  project_id: number
  project_name: string
  severity_stats: SeverityStats
  issue_type_stats: Record<string, number>
  coverage_summary: Record<string, unknown>
  metrics_summary: MetricsSummary
  degradation_summary: Record<string, unknown>
  verified_issues: IssueDetail[]
  rejected_issues: IssueDetail[]
  review_plan: Record<string, unknown>[]
  llm_call_count: number
  input_tokens: number
  output_tokens: number
  estimated_cost: string | null
  cost_status: string
  stop_reason: string | null
  started_at: string | null
  finished_at: string | null
}

export interface IssueDetail {
  id: number
  task_id: number
  fingerprint: string
  title: string
  category: string
  issue_type: string
  risk_level: 'High' | 'Medium' | 'Low'
  rule_id: string | null
  cwe_id: string | null
  relative_path: string
  start_line: number
  end_line: number
  evidence: string
  description: string
  reason: string
  suggestion: string
  fixed_example: string | null
  confidence: number
  evidence_status: string
  critic_decision: string | null
  critic_reason: string | null
  needs_human_review: boolean
  review_round: number
  status: string
  created_at: string | null
}

export interface ReportAPIResponse {
  task_id: number
  project_id: number
  summary: string | null
  report_content: string
  severity_stats: SeverityStats
  issue_type_stats: Record<string, number>
  coverage_summary: Record<string, unknown>
  metrics_summary: MetricsSummary
  degradation_summary: Record<string, unknown>
  created_at: string | null
}
