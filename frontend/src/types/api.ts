export interface ApiErrorResponse {
  code: string;
  message: string;
  request_id: string;
  details: Record<string, unknown>;
}

export interface ApiResult<T> {
  data: T;
  requestId: string;
}
