<script setup lang="ts">
/** Issue detail drawer — shows evidence, reason, suggestion, and code. */
import { computed } from 'vue'
import type { IssueDetail } from '@/types/report'

const props = defineProps<{
  visible: boolean
  issue: IssueDetail | null
  taskId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const visibleModel = computed({
  get: () => props.visible,
  set: (v) => emit('update:visible', v),
})

function copyEvidence() {
  if (props.issue?.evidence) {
    navigator.clipboard.writeText(props.issue.evidence)
  }
}
</script>

<template>
  <el-drawer
    v-model="visibleModel"
    :title="issue?.title ?? 'Issue Detail'"
    size="600px"
    direction="rtl"
  >
    <template v-if="issue">
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
        <el-tag type="info" style="margin-left: 8px">{{
          issue.category
        }}</el-tag>
        <el-tag v-if="issue.cwe_id" style="margin-left: 8px">{{
          issue.cwe_id
        }}</el-tag>
        <span
          v-if="issue.needs_human_review"
          style="margin-left: 8px; color: #e6a23c"
        >
          ⚠ Needs human review
        </span>
      </div>

      <div class="issue-section">
        <h4>File & Lines</h4>
        <code
          >{{ issue.relative_path }} L{{ issue.start_line }}-L{{
            issue.end_line
          }}</code
        >
      </div>

      <div class="issue-section">
        <h4>Description</h4>
        <p>{{ issue.description }}</p>
      </div>

      <div class="issue-section">
        <h4>
          Evidence
          <el-button size="small" text @click="copyEvidence">📋 Copy</el-button>
        </h4>
        <pre class="code-block"><code>{{ issue.evidence }}</code></pre>
      </div>

      <div class="issue-section">
        <h4>Reason</h4>
        <p>{{ issue.reason }}</p>
      </div>

      <div class="issue-section">
        <h4>Suggestion</h4>
        <p>{{ issue.suggestion }}</p>
      </div>

      <div v-if="issue.fixed_example" class="issue-section">
        <h4>Fixed Example</h4>
        <pre class="code-block"><code>{{ issue.fixed_example }}</code></pre>
      </div>

      <div class="issue-section">
        <h4>Details</h4>
        <ul class="detail-list">
          <li><strong>Rule:</strong> {{ issue.rule_id ?? 'N/A' }}</li>
          <li>
            <strong>Confidence:</strong>
            {{ (issue.confidence * 100).toFixed(0) }}%
          </li>
          <li>
            <strong>Critic:</strong> {{ issue.critic_decision ?? 'pending' }}
          </li>
          <li v-if="issue.critic_reason">
            <strong>Critic reason:</strong> {{ issue.critic_reason }}
          </li>
          <li><strong>Evidence status:</strong> {{ issue.evidence_status }}</li>
          <li><strong>Review round:</strong> {{ issue.review_round }}</li>
          <li>
            <strong>Fingerprint:</strong> <code>{{ issue.fingerprint }}</code>
          </li>
        </ul>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.issue-meta {
  margin-bottom: 16px;
}
.issue-section {
  margin-bottom: 20px;
}
.issue-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
  color: #303133;
}
.code-block {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
}
.code-block code {
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.detail-list {
  list-style: none;
  padding: 0;
}
.detail-list li {
  padding: 4px 0;
  font-size: 13px;
}
</style>
