import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { fetchReadiness } from "@/api/health";
import HomeView from "@/views/HomeView.vue";

vi.mock("@/api/health", () => ({
  fetchReadiness: vi.fn(),
}));

describe("HomeView", () => {
  it("checks and displays backend readiness on mount", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue({
      data: {
        status: "ready",
        service: "CodeReview Agent",
        version: "0.1.0",
        checks: { configuration: "ok" },
      },
      requestId: "view-request",
    });

    const wrapper = mount(HomeView, {
      global: {
        plugins: [createPinia()],
      },
    });
    await flushPromises();

    expect(fetchReadiness).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("API 已就绪");
    expect(wrapper.text()).toContain("CodeReview Agent");
    expect(wrapper.text()).toContain("Request ID: view-request");
  });
});
