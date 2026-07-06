import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { ApiError } from "@/api/client";
import { fetchReadiness } from "@/api/health";
import type { ReadyHealthResponse } from "@/types/health";

export type HealthPhase = "idle" | "loading" | "ready" | "error";

export const useHealthStore = defineStore("health", () => {
  const phase = ref<HealthPhase>("idle");
  const readiness = ref<ReadyHealthResponse | null>(null);
  const requestId = ref<string | null>(null);
  const errorMessage = ref<string | null>(null);
  const lastCheckedAt = ref<Date | null>(null);

  const isReady = computed(() => phase.value === "ready");

  async function refresh(): Promise<void> {
    phase.value = "loading";
    errorMessage.value = null;

    try {
      const result = await fetchReadiness();
      readiness.value = result.data;
      requestId.value = result.requestId;
      phase.value = "ready";
    } catch (error: unknown) {
      readiness.value = null;
      if (error instanceof ApiError) {
        requestId.value = error.requestId;
        errorMessage.value = `${error.code}: ${error.message}`;
      } else {
        requestId.value = null;
        errorMessage.value =
          error instanceof Error ? error.message : "无法连接后端服务";
      }
      phase.value = "error";
    } finally {
      lastCheckedAt.value = new Date();
    }
  }

  return {
    phase,
    readiness,
    requestId,
    errorMessage,
    lastCheckedAt,
    isReady,
    refresh,
  };
});
