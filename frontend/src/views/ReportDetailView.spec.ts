import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchIssues, fetchReport, fetchReportMarkdown } from '@/api/reports'
import { fetchReview } from '@/api/workflow'
import ReportDetailView from '@/views/ReportDetailView.vue'

const push = vi.fn()

vi.mock('@/api/reports', () => ({
  fetchIssues: vi.fn(),
  fetchReport: vi.fn(),
  fetchReportMarkdown: vi.fn(),
}))

vi.mock('@/api/workflow', () => ({
  fetchReview: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { taskId: '9' } }),
  useRouter: () => ({ push }),
}))

const stubs = {
  ElAlert: {
    props: ['title'],
    template: '<div role="alert">{{ title }}<slot /></div>',
  },
  ElButton: {
    template: '<button><slot /></button>',
  },
  ElSkeleton: {
    template: '<div data-test="skeleton" />',
  },
  ElTag: {
    template: '<span><slot /></span>',
  },
}

describe('ReportDetailView', () => {
  beforeEach(() => {
    push.mockReset()
    vi.clearAllMocks()
    vi.mocked(fetchReportMarkdown).mockReset()
  })

  it('shows failed task state without requesting missing report data', async () => {
    vi.mocked(fetchReview).mockResolvedValue({
      id: 9,
      project_id: 4,
      status: 'failed',
      review_mode: 'comprehensive',
      current_stage: 'file_scan',
      progress: 15,
      error_code: 'REVIEW_PIPELINE_FAILED',
      error_message: 'index store unavailable',
      fallback_reason: null,
    })

    const wrapper = mount(ReportDetailView, {
      global: { stubs },
    })
    await flushPromises()

    expect(fetchReview).toHaveBeenCalledWith(9)
    expect(fetchReport).not.toHaveBeenCalled()
    expect(fetchIssues).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('failed')
    expect(wrapper.text()).toContain('index store unavailable')
  })
})
