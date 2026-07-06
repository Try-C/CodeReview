export interface ReadyHealthResponse {
  status: 'ready'
  service: string
  version: string
  checks: Record<string, 'ok' | 'error'>
}
