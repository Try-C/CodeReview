<script setup lang="ts">
import {
  ElAlert,
  ElButton,
  ElMessage,
  ElProgress,
  ElSkeleton,
  ElTag,
} from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, clearAuth } from '@/api/client'
import { cancelReview, fetchReview } from '@/api/workflow'
import type { ReviewTask } from '@/types/workflow'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)
const task = ref<ReviewTask | null>(null)
const loadError = ref('')
const loading = ref(true)

let eventSource: EventSource | undefined
let pollTimer: number | undefined

const completed = computed(
  () =>
    task.value?.status === 'success' ||
    task.value?.status === 'partial_success',
)
const terminalFailure = computed(
  () => task.value?.status === 'failed' || task.value?.status === 'cancelled',
)
const isRunning = computed(
  () => task.value !== null && !completed.value && !terminalFailure.value,
)

const statusType = computed(() => {
  if (completed.value) return 'success'
  if (terminalFailure.value) return 'danger'
  return 'primary'
})

const stageLabels: Record<string, string> = {
  pending: '等待 Worker',
  scanning: '扫描文件',
  parsing: '解析代码',
  indexing: '构建索引',
  planning: '制定审查计划',
  reviewing: '审查代码',
  verifying: '验证证据',
  reporting: '生成报告',
  success: '审查完成',
  partial_success: '部分完成',
  failed: '审查失败',
  cancelled: '已取消',
  cancel_requested: '正在取消',
}

const stageName = computed(() => {
  const key = task.value?.current_stage ?? task.value?.status
  if (!key) return '—'
  return stageLabels[key] ?? key
})

/* ── SSE connection ── */
function connectSSE() {
  if (eventSource) return

  const token = localStorage.getItem('access_token')
  const base = import.meta.env.VITE_API_BASE_URL?.trim() ?? ''
  const url = `${base}/api/v1/reviews/${taskId}/events?token=${encodeURIComponent(token ?? '')}`

  eventSource = new EventSource(url)

  eventSource.addEventListener('status', (e) => {
    try {
      const payload = JSON.parse(e.data) as Partial<ReviewTask>
      if (task.value) {
        task.value = { ...task.value, ...payload }
      }
    } catch {
      /* ignore malformed events */
    }
  })

  eventSource.addEventListener('final', () => {
    closeSSE()
    void pollTask()
  })

  eventSource.addEventListener('error', () => {
    /* SSE may fail due to proxy / network; fall back to polling */
    closeSSE()
    startPolling()
  })
}

function closeSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = undefined
  }
}

/* ── Polling fallback ── */
async function pollTask() {
  try {
    task.value = await fetchReview(taskId)
    loadError.value = ''
    if (completed.value || terminalFailure.value) {
      closeSSE()
      stopPolling()
    }
  } catch (error) {
    loadError.value =
      error instanceof Error ? error.message : '无法获取任务进度'
    if (error instanceof ApiError && error.status === 401) {
      clearAuth()
      stopPolling()
      return
    }
    /* Don't stop polling on transient errors */
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => void pollTask(), 1500)
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

/* ── Cancel ── */
const cancelling = ref(false)

async function doCancel() {
  cancelling.value = true
  try {
    task.value = await cancelReview(taskId)
    ElMessage.info('正在取消审查…')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '取消失败')
  } finally {
    cancelling.value = false
  }
}

/* ── Manual retry ── */
async function retry() {
  loading.value = true
  loadError.value = ''
  await pollTask()
  loading.value = false
  if (task.value && isRunning.value) {
    connectSSE()
    startPolling()
  }
}

/* ── Lifecycle ── */
onMounted(async () => {
  if (!Number.isInteger(taskId) || taskId <= 0) {
    loadError.value = '无效的任务编号'
    loading.value = false
    return
  }
  await pollTask()
  loading.value = false

  /* Task loaded — decide on updates */
  if (task.value) {
    if (completed.value || terminalFailure.value) {
      if (completed.value) {
        ElMessage.success('审查完成，报告已生成')
      }
    } else {
      connectSSE()
      startPolling()
    }
  }
})

onUnmounted(() => {
  closeSSE()
  stopPolling()
})

function viewReport() {
  void router.push({ name: 'report', params: { taskId } })
}

function returnHome() {
  void router.push({ name: 'home' })
}
</script>

<template>
  <div class="page-container">
    <p class="eyebrow">LIVE REVIEW</p>
    <div class="page-title-row">
      <div>
        <h1>代码审查进度</h1>
        <p class="page-subtitle">任务 #{{ taskId }}</p>
      </div>
      <ElTag v-if="task" :type="statusType" effect="dark">
        {{ task.status }}
      </ElTag>
    </div>

    <!-- Loading skeleton -->
    <ElSkeleton
      v-if="loading"
      :rows="4"
      animated
      :throttle="0"
      style="margin-top: 16px"
    />

    <!-- Error with retry -->
    <template v-if="!loading && loadError">
      <ElAlert :title="loadError" type="error" :closable="false" show-icon />
      <div class="actions" style="margin-top: 20px">
        <ElButton type="primary" @click="retry">重新加载</ElButton>
        <ElButton @click="returnHome">返回首页</ElButton>
      </div>
    </template>

    <!-- Task loaded but API returned nothing (shouldn't happen normally) -->
    <template v-if="!loading && !loadError && !task">
      <ElAlert
        title="未获取到任务数据，请确认任务是否存在或后端服务是否正常"
        type="warning"
        :closable="false"
        show-icon
      />
      <div class="actions" style="margin-top: 20px">
        <ElButton type="primary" @click="retry">重新加载</ElButton>
        <ElButton @click="returnHome">返回首页</ElButton>
      </div>
    </template>

    <!-- Task content -->
    <template v-if="task">
      <ElProgress
        :percentage="task.progress"
        :status="
          completed ? 'success' : terminalFailure ? 'exception' : undefined
        "
        :stroke-width="18"
        style="margin-top: 8px"
      />

      <div class="stage-card">
        <span>当前阶段</span>
        <strong>{{ stageName }}</strong>
        <p v-if="task.fallback_reason">降级原因：{{ task.fallback_reason }}</p>
        <p v-if="task.error_message">错误：{{ task.error_message }}</p>
      </div>

      <!-- Still-loading hint while polling recovers from transient error -->
      <p
        v-if="loadError && isRunning"
        style="color: var(--muted); font-size: 13px; margin: 12px 0 0"
      >
        ⚠ 获取进度时暂时出错：{{ loadError }}。正在自动重试…
      </p>

      <div class="actions">
        <ElButton v-if="completed" type="primary" @click="viewReport">
          查看审查报告
        </ElButton>
        <ElButton
          v-if="isRunning"
          type="danger"
          :loading="cancelling"
          @click="doCancel"
        >
          取消审查
        </ElButton>
        <ElButton @click="returnHome">返回首页</ElButton>
      </div>
    </template>
  </div>
</template>
