import { getJson } from "@/api/client";
import type { ApiResult } from "@/types/api";
import type { ReadyHealthResponse } from "@/types/health";

export function fetchReadiness(): Promise<ApiResult<ReadyHealthResponse>> {
  return getJson<ReadyHealthResponse>("/api/v1/health/ready");
}
