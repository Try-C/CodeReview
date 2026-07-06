<script setup lang="ts">
/** Real-time task progress display via SSE per spec §15.5. */
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)

interface ProgressEvent {
  id: number
  event_type: string
  stage?: string
  progress?: number
  message?: string
}

const events = ref<ProgressEvent[]>([])
const currentStage = ref('')
const currentProgress = ref(0)
const currentMessage = ref('')
const completed = ref(false)

let eventSource: EventSource | null = null

onMounted(() => {
  const token = localStorage.getItem('access_token') ?? ''
  const params = new URLSearchParams({ token })
  const url = `/api/v1/reviews/${taskId}/events?${params.toString()}`

  eventSource = new EventSource(url)

  eventSource.addEventListener('progress', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data)
      events.value.push(data)
      currentStage.value = data.stage ?? currentStage.value
      currentProgress.value = data.progress ?? currentProgress.value
      currentMessage.value = data.message ?? currentMessage.value
      if (data.event_type === 'final' || data.stage === 'reporting') {
        completed.value = true
      }
    } catch {
      // ignore parse errors on heartbeat
    }
  })

  eventSource.addEventListener('final', () => {
    completed.value = true
    ElMessage.success('Review completed!')
    eventSource?.close()
  })

  eventSource.onerror = () => {
    if (completed.value) {
      eventSource?.close()
    }
  }
})

onUnmounted(() => {
  eventSource?.close()
})

function viewReport() {
  router.push({ name: 'report', params: { taskId } })
}

const stageLabels: Record<string, string> = {
  scanning: 'Scanning files',
  parsing: 'Parsing code',
  indexing: 'Building index',
  planning: 'Planning review',
  reviewing: 'Reviewing code',
  verifying: 'Verifying evidence',
  reporting: 'Generating report',
}
</script>

<template>
  <div class="progress-container">
    <h1>Review Progress</h1>
    <p class="subtitle">Task #{{ taskId }}</p>

    <div class="progress-bar-wrapper">
      <el-progress
        :percentage="currentProgress"
        :status="completed ? 'success' : undefined"
        :stroke-width="20"
      />
    </div>

    <div class="stage-info">
      <p v-if="currentStage">
        <strong>Stage:</strong> {{ stageLabels[currentStage] ?? currentStage }}
      </p>
      <p v-if="currentMessage"><strong>Message:</strong> {{ currentMessage }}</p>
    </div>

    <div v-if="completed" class="actions">
      <el-button type="primary" @click="viewReport">
        View Report
      </el-button>
    </div>

    <section v-if="events.length" class="event-log">
      <h2>Event Log</h2>
      <div v-for="evt in events" :key="evt.id" class="event-item">
        <span class="event-id">#{{ evt.id }}</span>
        <span class="event-type">{{ evt.event_type }}</span>
        <span v-if="evt.stage" class="event-stage">{{ evt.stage }}</span>
        <span v-if="evt.progress !== undefined" class="event-progress">{{ evt.progress }}%</span>
        <span v-if="evt.message" class="event-msg">{{ evt.message }}</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.progress-container { max-width: 700px; margin: 0 auto; padding: 24px; }
h1 { font-size: 22px; margin-bottom: 4px; }
.subtitle { color: #909399; font-size: 14px; margin-bottom: 24px; }
.progress-bar-wrapper { margin-bottom: 16px; }
.stage-info p { margin: 4px 0; font-size: 14px; }
.actions { margin-top: 20px; }

.event-log { margin-top: 32px; }
.event-log h2 { font-size: 16px; margin-bottom: 8px; }
.event-item { padding: 4px 8px; font-size: 13px; border-bottom: 1px solid #ebeef5; display: flex; gap: 12px; }
.event-id { color: #909399; min-width: 40px; }
.event-type { font-weight: 600; min-width: 80px; }
.event-stage { color: #409eff; }
.event-progress { color: #67c23a; }
.event-msg { color: #606266; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
