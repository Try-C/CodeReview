export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface UploadManifestItem {
  relative_path: string
  declared_size: number
  status: 'pending' | 'uploaded' | 'skipped' | 'failed'
  language: 'java' | 'python' | null
  reason: string | null
}

export interface UploadSession {
  upload_id: string
  project_id: number | null
  project_name: string
  status: 'created' | 'uploading' | 'completed'
  total_files: number
  uploaded_files: number
  skipped_files: number
  failed_files: number
  manifest: UploadManifestItem[]
}

export interface ProjectSummary {
  id: number
  project_name: string
  total_files: number
  total_lines: number
  status: string
}

export interface UploadCompleteResponse {
  upload: UploadSession
  project: ProjectSummary
}

export type ReviewMode =
  'security' | 'bug' | 'performance' | 'maintainability' | 'comprehensive'

export type TaskStatus =
  | 'pending'
  | 'scanning'
  | 'parsing'
  | 'indexing'
  | 'planning'
  | 'reviewing'
  | 'verifying'
  | 'reporting'
  | 'success'
  | 'partial_success'
  | 'failed'
  | 'cancel_requested'
  | 'cancelled'

export interface ReviewTask {
  id: number
  project_id: number
  status: TaskStatus
  review_mode: ReviewMode
  current_stage: string | null
  progress: number
  error_code: string | null
  error_message: string | null
  fallback_reason: string | null
}

export interface ProjectFileSelection {
  file: File
  relativePath: string
}
