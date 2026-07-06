<script setup lang="ts">
/** Issue detail drawer — evidence, reason, suggestion, feedback, syntax highlighting. */
import { ElButton, ElMessage, ElTag } from 'element-plus'
import { computed, nextTick, ref, watch } from 'vue'
import hljs from 'highlight.js/lib/core'
import java from 'highlight.js/lib/languages/java'
import python from 'highlight.js/lib/languages/python'
import 'highlight.js/styles/github.css'

import { submitFeedback } from '@/api/reports'
import type { FeedbackStatus } from '@/api/reports'
import type { IssueDetail } from '@/types/report'

hljs.registerLanguage('java', java)
hljs.registerLanguage('python', python)

const props = defineProps<{
  visible: boolean
  issue: IssueDetail | null
  taskId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'feedback-saved': []
}>()

const visibleModel = computed({
  get: () => props.visible,
  set: (v) => emit('update:visible', v),
})

const feedbackLoading = ref(false)

/* ── Detect language from file extension ── */
const codeLanguage = computed(() => {
  if (!props.issue?.relative_path) return undefined
  if (props.issue.relative_path.endsWith('.py')) return 'python'
  if (props.issue.relative_path.endsWith('.java')) return 'java'
  return undefined
})

/* ── Highlight code blocks after render ── */
function highlight(el: HTMLElement | null) {
  if (!el) return
  const blocks = el.querySelectorAll<HTMLElement>('pre code[data-lang]')
  blocks.forEach((block) => {
    const lang = block.dataset.lang
    if (lang && hljs.getLanguage(lang)) {
      try {
        const result = hljs.highlight(block.textContent ?? '', {
          language: lang,
        })
        block.innerHTML = result.value
        block.classList.add('hljs')
      } catch {
        /* leave as plain text */
      }
    }
  })
}

/* ── Re-highlight when issue changes ── */
const drawerRef = ref<HTMLElement | null>(null)
watch(
  () => props.issue?.id,
  () => {
    if (props.visible) {
      void nextTick(() => highlight(drawerRef.value))
    }
  },
)

watch(
  () => props.visible,
  (v) => {
    if (v) void nextTick(() => highlight(drawerRef.value))
  },
)

/* ── Copy evidence ── */
async function copyEvidence() {
  if (props.issue?.evidence) {
    try {
      await navigator.clipboard.writeText(props.issue.evidence)
      ElMessage.success('证据已复制')
    } catch {
      /* clipboard might not be available */
      ElMessage.info('复制失败，请手动选择文本')
    }
  }
}

/* ── Feedback ── */
async function doFeedback(status: FeedbackStatus) {
  if (!props.issue) return
  feedbackLoading.value = true
  try {
    await submitFeedback(props.issue.id, status)
    ElMessage.success(
      status === 'confirmed'
        ? '已标记为确认'
        : status === 'false_positive'
          ? '已标记为误报'
          : '已标记为待复核',
    )
    emit('feedback-saved')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '反馈提交失败')
  } finally {
    feedbackLoading.value = false
  }
}
</script>

<template>
  <el-drawer
    ref="drawerRef"
    v-model="visibleModel"
    :title="issue?.title ?? 'Issue Detail'"
    size="620px"
    direction="rtl"
  >
    <template v-if="issue">
      <!-- Meta tags -->
      <div class="issue-meta">
        <el-tag
          :type="
            issue.risk_level === 'High'
              ? 'danger'
              : issue.risk_level === 'Medium'
                ? 'warning'
                : 'success'
          "
        >
          {{ issue.risk_level }}
        </el-tag>
        <el-tag type="info" style="margin-left: 8px">
          {{ issue.category }}
        </el-tag>
        <el-tag v-if="issue.cwe_id" style="margin-left: 8px">
          {{ issue.cwe_id }}
        </el-tag>
        <span
          v-if="issue.needs_human_review"
          style="margin-left: 8px; color: var(--warning); font-size: 13px"
        >
          ⚠ 需人工复核
        </span>
      </div>

      <!-- File & Lines -->
      <div class="issue-section">
        <h4>文件位置</h4>
        <code class="file-ref">
          {{ issue.relative_path }} L{{ issue.start_line }}-L{{
            issue.end_line
          }}
        </code>
      </div>

      <!-- Description -->
      <div class="issue-section">
        <h4>问题描述</h4>
        <p>{{ issue.description }}</p>
      </div>

      <!-- Evidence with syntax highlighting -->
      <div class="issue-section">
        <h4>
          证据
          <el-button size="small" text @click="copyEvidence">📋 复制</el-button>
        </h4>
        <pre
          class="code-block"
        ><code :data-lang="codeLanguage">{{ issue.evidence }}</code></pre>
      </div>

      <!-- Reason -->
      <div class="issue-section">
        <h4>原因</h4>
        <p>{{ issue.reason }}</p>
      </div>

      <!-- Suggestion -->
      <div class="issue-section">
        <h4>建议</h4>
        <p>{{ issue.suggestion }}</p>
      </div>

      <!-- Fixed Example -->
      <div v-if="issue.fixed_example" class="issue-section">
        <h4>修复示例</h4>
        <pre
          class="code-block"
        ><code :data-lang="codeLanguage">{{ issue.fixed_example }}</code></pre>
      </div>

      <!-- Technical details -->
      <div class="issue-section">
        <h4>技术细节</h4>
        <ul class="detail-list">
          <li><strong>规则:</strong> {{ issue.rule_id ?? 'N/A' }}</li>
          <li>
            <strong>置信度:</strong> {{ (issue.confidence * 100).toFixed(0) }}%
          </li>
          <li>
            <strong>Critic:</strong> {{ issue.critic_decision ?? 'pending' }}
          </li>
          <li v-if="issue.critic_reason">
            <strong>Critic 理由:</strong> {{ issue.critic_reason }}
          </li>
          <li><strong>证据状态:</strong> {{ issue.evidence_status }}</li>
          <li><strong>审查轮次:</strong> {{ issue.review_round }}</li>
          <li>
            <strong>指纹:</strong> <code>{{ issue.fingerprint }}</code>
          </li>
        </ul>
      </div>

      <!-- Feedback buttons -->
      <div class="feedback-bar">
        <el-button
          type="success"
          :loading="feedbackLoading"
          :disabled="issue.status === 'confirmed'"
          @click="doFeedback('confirmed')"
        >
          ✓ 确认
        </el-button>
        <el-button
          type="danger"
          :loading="feedbackLoading"
          :disabled="issue.status === 'false_positive'"
          @click="doFeedback('false_positive')"
        >
          ✗ 误报
        </el-button>
        <el-button
          type="warning"
          :loading="feedbackLoading"
          :disabled="issue.status === 'needs_review'"
          @click="doFeedback('needs_review')"
        >
          ⚠ 需复核
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.file-ref {
  display: inline-block;
  padding: 4px 10px;
  background: rgba(13, 143, 115, 0.07);
  border-radius: 4px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 13px;
  color: var(--accent-deep);
}

.feedback-bar {
  display: flex;
  gap: 10px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
</style>
