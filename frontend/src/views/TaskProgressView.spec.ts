import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cancelReview, fetchReview } from '@/api/workflow'
import TaskProgressView from '@/views/TaskProgressView.vue'

const push = vi.fn()

vi.mock('@/api/workflow', () => ({
  cancelReview: vi.fn(),
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
  ElProgress: {
    props: ['percentage'],
    template: '<div data-test="progress">{{ percentage }}</div>',
  },
  ElSkeleton: {
    template: '<div data-test="skeleton" />',
  },
  ElTag: {
    template: '<span><slot /></span>',
  },
}

describe('TaskProgressView', () => {
  beforeEach(() => {
    push.mockReset()
    vi.clearAllMocks()
    vi.mocked(cancelReview).mockReset()
  })

  it('renders terminal failure details instead of a blank progress page', async () => {
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

    const wrapper = mount(TaskProgressView, {
      global: { stubs },
    })
    await flushPromises()

    expect(fetchReview).toHaveBeenCalledWith(9)
    expect(wrapper.text()).toContain('failed')
    expect(wrapper.text()).toContain('file_scan')
    expect(wrapper.text()).toContain('index store unavailable')
  })
})
