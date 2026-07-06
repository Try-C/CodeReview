import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchReadiness } from '@/api/health'
import {
  completeUpload,
  createReview,
  initializeUpload,
  login,
  register,
  uploadAcceptedFiles,
} from '@/api/workflow'
import HomeView from '@/views/HomeView.vue'

const push = vi.fn()

vi.mock('@/api/health', () => ({
  fetchReadiness: vi.fn(),
}))

vi.mock('@/api/workflow', () => ({
  completeUpload: vi.fn(),
  createReview: vi.fn(),
  initializeUpload: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  uploadAcceptedFiles: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

describe('HomeView', () => {
  beforeEach(() => {
    localStorage.clear()
    push.mockReset()
    vi.clearAllMocks()
  })

  it('checks and displays backend readiness on mount', async () => {
    vi.mocked(fetchReadiness).mockResolvedValue({
      data: {
        status: 'ready',
        service: 'CodeReview Agent',
        version: '0.1.0',
        checks: {
          configuration: 'ok',
          database: 'ok',
          redis: 'ok',
        },
      },
      requestId: 'view-request',
    })

    const wrapper = mount(HomeView, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    expect(fetchReadiness).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('API 已就绪')
    expect(wrapper.text()).toContain('CodeReview Agent')
    expect(wrapper.text()).toContain('PostgreSQL')
    expect(wrapper.text()).toContain('Redis')
    expect(wrapper.text()).toContain('Request ID: view-request')
  })

  it('registers, uploads a selected folder, and opens task progress', async () => {
    vi.mocked(fetchReadiness).mockResolvedValue({
      data: {
        status: 'ready',
        service: 'CodeReview Agent',
        version: '0.1.0',
        checks: {
          configuration: 'ok',
          database: 'ok',
          redis: 'ok',
        },
      },
      requestId: 'view-request',
    })
    vi.mocked(register).mockResolvedValue()
    vi.mocked(login).mockResolvedValue({
      access_token: 'local-token',
      token_type: 'bearer',
      expires_in: 1800,
    })
    vi.mocked(initializeUpload).mockResolvedValue({
      upload_id: 'upload-1',
      project_id: null,
      project_name: 'demo',
      status: 'created',
      total_files: 1,
      uploaded_files: 0,
      skipped_files: 0,
      failed_files: 0,
      manifest: [
        {
          relative_path: 'src/main.py',
          declared_size: 12,
          status: 'pending',
          language: 'python',
          reason: null,
        },
      ],
    })
    vi.mocked(uploadAcceptedFiles).mockResolvedValue({
      upload_id: 'upload-1',
      project_id: null,
      project_name: 'demo',
      status: 'uploading',
      total_files: 1,
      uploaded_files: 1,
      skipped_files: 0,
      failed_files: 0,
      manifest: [],
    })
    vi.mocked(completeUpload).mockResolvedValue({
      upload: {
        upload_id: 'upload-1',
        project_id: 4,
        project_name: 'demo',
        status: 'completed',
        total_files: 1,
        uploaded_files: 1,
        skipped_files: 0,
        failed_files: 0,
        manifest: [],
      },
      project: {
        id: 4,
        project_name: 'demo',
        total_files: 1,
        total_lines: 1,
        status: 'ready',
      },
    })
    vi.mocked(createReview).mockResolvedValue({
      id: 9,
      project_id: 4,
      status: 'pending',
      review_mode: 'comprehensive',
      current_stage: null,
      progress: 0,
      error_code: null,
      error_message: null,
      fallback_reason: null,
    })

    const wrapper = mount(HomeView, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    await wrapper
      .find('input[placeholder="用户名（至少 3 位）"]')
      .setValue('reviewer')
    await wrapper
      .find('input[placeholder="密码（至少 8 位）"]')
      .setValue('secure-password')
    const registerButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('注册并登录'))
    await registerButton?.trigger('click')
    await flushPromises()

    const file = new File(['print("ok")'], 'main.py')
    Object.defineProperty(file, 'webkitRelativePath', {
      value: 'demo/src/main.py',
    })
    const folderInput = wrapper.find('input[type="file"]')
    Object.defineProperty(folderInput.element, 'files', {
      configurable: true,
      value: [file],
    })
    await folderInput.trigger('change')

    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('上传并开始审查'))
    await startButton?.trigger('click')
    await flushPromises()

    expect(register).toHaveBeenCalledWith('reviewer', 'secure-password')
    expect(initializeUpload).toHaveBeenCalledWith(
      'demo',
      expect.arrayContaining([
        expect.objectContaining({ relativePath: 'src/main.py' }),
      ]),
    )
    expect(createReview).toHaveBeenCalledWith(4, 'comprehensive')
    expect(push).toHaveBeenCalledWith({
      name: 'task-progress',
      params: { taskId: 9 },
    })
  })
})
