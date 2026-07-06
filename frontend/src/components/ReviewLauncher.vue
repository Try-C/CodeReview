<script setup lang="ts">
/** Step 03: review launcher — mode select + submit. */
import {
  ElButton,
  ElCard,
  ElInput,
  ElMessage,
  ElOption,
  ElProgress,
  ElSelect,
} from 'element-plus'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, clearAuth } from '@/api/client'
import {
  completeUpload,
  createReview,
  initializeUpload,
  uploadAcceptedFiles,
} from '@/api/workflow'
import type { ProjectFileSelection, ReviewMode } from '@/types/workflow'

const props = defineProps<{
  isAuthenticated: boolean
  apiReady: boolean
  projectName: string
  selectedFiles: ProjectFileSelection[]
}>()

const emit = defineEmits<{
  'update:projectName': [value: string]
}>()

const router = useRouter()

const mode = ref<ReviewMode>('comprehensive')
const submitting = ref(false)
const message = ref('')
const uploadPct = ref(0)

const canSubmit = computed(() => {
  if (!props.isAuthenticated) return false
  if (!props.apiReady) return false
  if (!props.projectName.trim() || props.selectedFiles.length === 0)
    return false
  const supported = props.selectedFiles.filter(({ relativePath }) =>
    ['.py', '.java'].some((ext) => relativePath.endsWith(ext)),
  ).length
  return supported > 0
})

async function start() {
  if (!canSubmit.value) {
    ElMessage.warning('请先登录并选择包含 Java/Python 源码的文件夹')
    return
  }

  submitting.value = true
  uploadPct.value = 2
  try {
    message.value = '正在创建安全上传清单…'
    const initialized = await initializeUpload(
      props.projectName.trim(),
      props.selectedFiles,
    )
    const acceptedCount = initialized.manifest.filter(
      (item) => item.status === 'pending',
    ).length
    if (acceptedCount === 0) {
      throw new Error(
        '后端未接受任何 Java/Python 文件，请检查文件大小和目录内容',
      )
    }

    message.value = `正在上传 ${acceptedCount} 个源码文件…`
    await uploadAcceptedFiles(
      initialized,
      props.selectedFiles,
      (uploaded, total) => {
        uploadPct.value = Math.round((uploaded / total) * 75) + 10
      },
    )

    message.value = '正在完成项目并创建审查任务…'
    uploadPct.value = 90
    const completed = await completeUpload(initialized.upload_id)
    const task = await createReview(completed.project.id, mode.value)
    uploadPct.value = 100
    message.value = `任务 #${task.id} 已进入队列`
    await router.push({
      name: 'task-progress',
      params: { taskId: task.id },
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearAuth()
    }
    message.value = ''
    ElMessage.error(
      error instanceof Error ? error.message : '上传或创建审查失败',
    )
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-card class="workflow-card" shadow="never">
    <template #header>
      <div class="step-title">
        <span>03</span>
        <strong>开始审查</strong>
      </div>
    </template>

    <el-input
      :model-value="projectName"
      placeholder="项目名称"
      :disabled="submitting"
      @update:model-value="emit('update:projectName', $event)"
    />
    <el-select
      v-model="mode"
      class="form-control full-width"
      :disabled="submitting"
      aria-label="审查模式"
    >
      <el-option label="综合审查" value="comprehensive" />
      <el-option label="安全" value="security" />
      <el-option label="缺陷" value="bug" />
      <el-option label="性能" value="performance" />
      <el-option label="可维护性" value="maintainability" />
    </el-select>
    <el-button
      class="full-width form-control"
      type="primary"
      size="large"
      :disabled="!canSubmit"
      :loading="submitting"
      @click="start"
    >
      上传并开始审查
    </el-button>
    <el-progress
      v-if="submitting || uploadPct > 0"
      class="upload-progress"
      :percentage="uploadPct"
      :status="uploadPct === 100 ? 'success' : undefined"
    />
    <p v-if="message" class="workflow-message">
      {{ message }}
    </p>
  </el-card>
</template>
