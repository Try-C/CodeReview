<script setup lang="ts">
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElSkeleton,
  ElTag,
} from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { useHealthStore } from '@/stores/health'
import type { ProjectFileSelection } from '@/types/workflow'
import LoginPanel from '@/components/LoginPanel.vue'
import FolderUploader from '@/components/FolderUploader.vue'
import ReviewLauncher from '@/components/ReviewLauncher.vue'

const healthStore = useHealthStore()

const authenticated = ref(Boolean(localStorage.getItem('access_token')))
const projectName = ref('')
const selectedFiles = ref<ProjectFileSelection[]>([])

const statusType = computed(() => {
  if (healthStore.phase === 'ready') return 'success'
  if (healthStore.phase === 'error') return 'danger'
  return 'info'
})

const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    idle: '等待检查',
    loading: '检查中',
    ready: 'API 已就绪',
    error: 'API 不可用',
  }
  return labels[healthStore.phase]
})

const checkedAt = computed(() => {
  if (!healthStore.lastCheckedAt) return '尚未检查'
  return healthStore.lastCheckedAt.toLocaleTimeString('zh-CN', {
    hour12: false,
  })
})

const checkLabels: Record<string, string> = {
  configuration: '配置',
  database: 'PostgreSQL',
  redis: 'Redis',
}

onMounted(() => {
  void healthStore.refresh()
})

function onAuthChange() {
  authenticated.value = Boolean(localStorage.getItem('access_token'))
}
</script>

<template>
  <!-- Hero -->
  <section class="hero">
    <div class="hero-copy">
      <p class="eyebrow">AI CODE REVIEW PLATFORM</p>
      <h1>让每一条审查结论<br />都能回到真实代码。</h1>
      <p class="hero-description">
        选择本地 Java/Python
        项目，平台会安全上传源码、构建混合检索索引，并生成带文件、行号和证据的审查报告。
      </p>
      <div class="principles" aria-label="项目核心原则">
        <span>真实证据</span>
        <span>有界执行</span>
        <span>量化评测</span>
      </div>
    </div>

    <!-- Status card -->
    <ElCard class="status-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <p class="card-kicker">SYSTEM STATUS</p>
            <h2>后端连接</h2>
          </div>
          <ElTag :type="statusType" effect="dark" round>
            {{ statusLabel }}
          </ElTag>
        </div>
      </template>

      <ElSkeleton v-if="healthStore.phase === 'loading'" :rows="4" animated />
      <ElAlert
        v-else-if="healthStore.phase === 'error'"
        :title="healthStore.errorMessage ?? '无法连接后端服务'"
        type="error"
        :closable="false"
        show-icon
      />
      <ElDescriptions v-else-if="healthStore.readiness" :column="1" border>
        <ElDescriptionsItem label="服务">
          {{ healthStore.readiness.service }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="版本">
          {{ healthStore.readiness.version }}
        </ElDescriptionsItem>
        <ElDescriptionsItem
          v-for="(checkStatus, checkName) in healthStore.readiness.checks"
          :key="checkName"
          :label="checkLabels[checkName] ?? checkName"
        >
          <ElTag
            :type="checkStatus === 'ok' ? 'success' : 'danger'"
            effect="plain"
            size="small"
          >
            {{ checkStatus }}
          </ElTag>
        </ElDescriptionsItem>
      </ElDescriptions>

      <div class="status-meta">
        <span>上次检查：{{ checkedAt }}</span>
        <span v-if="healthStore.requestId" class="request-id">
          Request ID: {{ healthStore.requestId }}
        </span>
      </div>
      <ElButton
        class="refresh-button"
        type="primary"
        :loading="healthStore.phase === 'loading'"
        @click="healthStore.refresh"
      >
        重新检查
      </ElButton>
    </ElCard>
  </section>

  <!-- 3-step workbench -->
  <section class="review-workbench" aria-labelledby="review-title">
    <div class="section-heading">
      <p class="eyebrow">START A REVIEW</p>
      <h2 id="review-title">上传本地项目并生成报告</h2>
    </div>

    <div class="workbench-grid">
      <LoginPanel @authenticated="onAuthChange" @logout="onAuthChange" />
      <FolderUploader
        :selected-files="selectedFiles"
        :project-name="projectName"
        @select="
          (files, name) => {
            selectedFiles = files
            projectName = name
          }
        "
      />
      <ReviewLauncher
        :is-authenticated="authenticated"
        :api-ready="healthStore.phase === 'ready'"
        :project-name="projectName"
        :selected-files="selectedFiles"
        @update:project-name="projectName = $event"
      />
    </div>
  </section>

  <!-- Pipeline intro -->
  <section class="pipeline" aria-labelledby="pipeline-title">
    <div class="section-heading">
      <p class="eyebrow">P0 PIPELINE</p>
      <h2 id="pipeline-title">从源码到证据化报告</h2>
    </div>
    <div class="pipeline-grid">
      <article>
        <span>01</span>
        <h3>Parse</h3>
        <p>Tree-sitter 解析 Java/Python，并保留路径、符号和行号。</p>
      </article>
      <article>
        <span>02</span>
        <h3>Retrieve</h3>
        <p>PostgreSQL 全文检索与向量检索通过 RRF 融合。</p>
      </article>
      <article>
        <span>03</span>
        <h3>Verify</h3>
        <p>确定性节点验证证据归属，再交由 Critic 语义复核。</p>
      </article>
      <article>
        <span>04</span>
        <h3>Report</h3>
        <p>汇总风险、覆盖范围、真实代码证据和模型调用指标。</p>
      </article>
    </div>
  </section>
</template>
