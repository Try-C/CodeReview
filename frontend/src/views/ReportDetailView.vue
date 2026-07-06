<script setup lang="ts">
/** Full review report page per spec §17.2. */
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchReport, fetchIssues, fetchReportMarkdown } from '@/api/reports'
import type { ReportAPIResponse, IssueDetail } from '@/types/report'
import IssueDetailDrawer from '@/components/IssueDetailDrawer.vue'

const route = useRoute()
const taskId = Number(route.params.taskId)
const report = ref<ReportAPIResponse | null>(null)
const issues = ref<IssueDetail[]>([])
const loading = ref(true)
const drawerVisible = ref(false)
const selectedIssue = ref<IssueDetail | null>(null)

onMounted(async () => {
  try {
    const [r, i] = await Promise.all([fetchReport(taskId), fetchIssues(taskId)])
    report.value = r
    issues.value = i
  } catch (e: unknown) {
    ElMessage.error(
      'Failed to load report: ' + (e instanceof Error ? e.message : String(e)),
    )
  } finally {
    loading.value = false
  }
})

function openIssue(issue: IssueDetail) {
  selectedIssue.value = issue
  drawerVisible.value = true
}

function getRiskColor(level: string) {
  return level === 'High'
    ? '#F56C6C'
    : level === 'Medium'
      ? '#E6A23C'
      : '#67C23A'
}

function getRiskIcon(level: string) {
  return level === 'High' ? '🔴' : level === 'Medium' ? '🟡' : '🟢'
}

async function downloadMarkdown() {
  try {
    const md = await fetchReportMarkdown(taskId)
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `report-${taskId}.md`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Report downloaded')
  } catch {
    ElMessage.error('Download failed')
  }
}
</script>

<template>
  <div class="report-container" v-loading="loading">
    <template v-if="report">
      <header class="report-header">
        <h1>Code Review Report</h1>
        <p class="subtitle">
          Task #{{ report.task_id }} &middot;
          {{
            report.created_at
              ? new Date(report.created_at).toLocaleString()
              : ''
          }}
        </p>
        <p v-if="report.summary" class="summary">{{ report.summary }}</p>
        <el-button
          @click="downloadMarkdown"
          size="small"
          style="margin-top: 8px"
        >
          ⬇ Export Markdown
        </el-button>
      </header>

      <!-- Severity stats -->
      <section class="stats-row">
        <div class="stat-card high">
          <span class="stat-count">{{ report.severity_stats.high }}</span>
          <span class="stat-label">High</span>
        </div>
        <div class="stat-card medium">
          <span class="stat-count">{{ report.severity_stats.medium }}</span>
          <span class="stat-label">Medium</span>
        </div>
        <div class="stat-card low">
          <span class="stat-count">{{ report.severity_stats.low }}</span>
          <span class="stat-label">Low</span>
        </div>
        <div class="stat-card total">
          <span class="stat-count">{{ report.severity_stats.total }}</span>
          <span class="stat-label">Total</span>
        </div>
      </section>

      <!-- Issue type distribution -->
      <section
        v-if="Object.keys(report.issue_type_stats).length"
        class="section"
      >
        <h2>Issue Types</h2>
        <el-tag
          v-for="(count, cat) in report.issue_type_stats"
          :key="cat"
          style="margin: 4px"
        >
          {{ cat }}: {{ count }}
        </el-tag>
      </section>

      <!-- Metrics -->
      <section class="section">
        <h2>Metrics</h2>
        <div class="metrics-grid">
          <span
            >LLM calls:
            <strong>{{ report.metrics_summary.llm_call_count }}</strong></span
          >
          <span
            >Input tokens:
            <strong>{{
              report.metrics_summary.input_tokens.toLocaleString()
            }}</strong></span
          >
          <span
            >Output tokens:
            <strong>{{
              report.metrics_summary.output_tokens.toLocaleString()
            }}</strong></span
          >
          <span
            >Cost:
            <strong>{{ report.metrics_summary.cost_display }}</strong></span
          >
          <span v-if="report.metrics_summary.elapsed_seconds">
            Duration:
            <strong>{{ report.metrics_summary.elapsed_seconds }}s</strong>
          </span>
          <span v-if="report.stop_reason">
            Stop reason: <strong>{{ report.stop_reason }}</strong>
          </span>
        </div>
      </section>

      <!-- Issues list -->
      <section class="section">
        <h2>Issues ({{ issues.length }})</h2>
        <el-table
          :data="issues"
          stripe
          @row-click="openIssue"
          style="cursor: pointer"
        >
          <el-table-column width="50">
            <template #default="{ row }">
              <span>{{ getRiskIcon(row.risk_level) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="title"
            label="Title"
            min-width="200"
            show-overflow-tooltip
          />
          <el-table-column prop="category" label="Category" width="120" />
          <el-table-column
            prop="issue_type"
            label="Type"
            width="140"
            show-overflow-tooltip
          />
          <el-table-column label="Risk" width="80">
            <template #default="{ row }">
              <span
                :style="{
                  color: getRiskColor(row.risk_level),
                  fontWeight: 'bold',
                }"
              >
                {{ row.risk_level }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="File" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.relative_path }} :{{ row.start_line }}
            </template>
          </el-table-column>
          <el-table-column prop="critic_decision" label="Critic" width="90" />
          <el-table-column label="Confidence" width="100">
            <template #default="{ row }">
              {{ (row.confidence * 100).toFixed(0) }}%
            </template>
          </el-table-column>
        </el-table>
      </section>

      <!-- Degradation -->
      <section
        v-if="Object.keys(report.degradation_summary).length"
        class="section"
      >
        <h2>Degradation</h2>
        <ul>
          <li v-for="(v, k) in report.degradation_summary" :key="k">
            <strong>{{ k }}</strong
            >: {{ v }}
          </li>
        </ul>
      </section>
    </template>

    <IssueDetailDrawer
      v-model:visible="drawerVisible"
      :issue="selectedIssue"
      :task-id="taskId"
    />
  </div>
</template>

<style scoped>
.report-container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px;
}
.report-header {
  margin-bottom: 24px;
}
.report-header h1 {
  font-size: 24px;
  margin-bottom: 4px;
}
.subtitle {
  color: #909399;
  font-size: 14px;
}
.summary {
  margin-top: 12px;
  padding: 12px 16px;
  background: #f0f9eb;
  border-left: 4px solid #67c23a;
  border-radius: 4px;
}

.stats-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}
.stat-card {
  flex: 1;
  text-align: center;
  padding: 16px;
  border-radius: 8px;
  color: #fff;
}
.stat-card.high {
  background: #f56c6c;
}
.stat-card.medium {
  background: #e6a23c;
}
.stat-card.low {
  background: #67c23a;
}
.stat-card.total {
  background: #409eff;
}
.stat-count {
  display: block;
  font-size: 32px;
  font-weight: 700;
}
.stat-label {
  font-size: 14px;
  opacity: 0.9;
}

.section {
  margin-bottom: 24px;
}
.section h2 {
  font-size: 18px;
  margin-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 8px;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}
</style>
