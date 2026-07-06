<script setup lang="ts">
/** Full review report page per spec §17.2. */
import { computed, ref, onMounted } from 'vue'
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

/* ── Filters ── */
const riskFilter = ref('')
const categoryFilter = ref('')
const issueSearch = ref('')
const currentPage = ref(1)
const pageSize = ref(15)

const stopReason = computed(() => {
  const value = report.value?.coverage_summary.stop_reason
  return typeof value === 'string' ? value : null
})

const filteredIssues = computed(() => {
  let list = issues.value
  if (riskFilter.value) {
    list = list.filter((i) => i.risk_level === riskFilter.value)
  }
  if (categoryFilter.value) {
    list = list.filter((i) => i.category === categoryFilter.value)
  }
  if (issueSearch.value) {
    const q = issueSearch.value.toLowerCase()
    list = list.filter(
      (i) =>
        i.title.toLowerCase().includes(q) ||
        i.relative_path.toLowerCase().includes(q) ||
        i.issue_type.toLowerCase().includes(q),
    )
  }
  return list
})

const pagedIssues = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredIssues.value.slice(start, start + pageSize.value)
})

const categories = computed(() => {
  const set = new Set(issues.value.map((i) => i.category))
  return [...set].sort()
})

async function loadData() {
  loading.value = true
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
}

onMounted(() => {
  void loadData()
})

function openIssue(issue: IssueDetail) {
  selectedIssue.value = issue
  drawerVisible.value = true
}

function onFilterChange() {
  currentPage.value = 1
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
    ElMessage.success('报告已下载')
  } catch {
    ElMessage.error('下载失败')
  }
}
</script>

<template>
  <div class="page-container wide" v-loading="loading">
    <template v-if="report">
      <!-- Header -->
      <header class="report-header">
        <h1>审查报告</h1>
        <p class="page-subtitle">
          Task #{{ report.task_id }} &middot;
          {{
            report.created_at
              ? new Date(report.created_at).toLocaleString()
              : ''
          }}
        </p>
        <div v-if="report.summary" class="report-summary">
          {{ report.summary }}
        </div>
        <el-button
          @click="downloadMarkdown"
          size="small"
          style="margin-top: 8px"
        >
          ⬇ 导出 Markdown
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
        class="report-section"
      >
        <h2>问题类型分布</h2>
        <el-tag
          v-for="(count, cat) in report.issue_type_stats"
          :key="cat"
          style="margin: 4px"
        >
          {{ cat }}: {{ count }}
        </el-tag>
      </section>

      <!-- Metrics -->
      <section class="report-section">
        <h2>运行指标</h2>
        <div class="metrics-grid">
          <span
            >LLM 调用:
            <strong>{{ report.metrics_summary.llm_call_count }}</strong></span
          >
          <span
            >输入 Tokens:
            <strong>{{
              report.metrics_summary.input_tokens.toLocaleString()
            }}</strong></span
          >
          <span
            >输出 Tokens:
            <strong>{{
              report.metrics_summary.output_tokens.toLocaleString()
            }}</strong></span
          >
          <span
            >费用:
            <strong>{{ report.metrics_summary.cost_display }}</strong></span
          >
          <span v-if="report.metrics_summary.elapsed_seconds">
            耗时: <strong>{{ report.metrics_summary.elapsed_seconds }}s</strong>
          </span>
          <span v-if="stopReason">
            停止原因: <strong>{{ stopReason }}</strong>
          </span>
        </div>
      </section>

      <!-- Issues list -->
      <section class="report-section">
        <h2>问题列表 ({{ issues.length }})</h2>

        <!-- Filter bar -->
        <div class="filter-bar">
          <el-input
            v-model="issueSearch"
            placeholder="搜索标题、文件、类型…"
            clearable
            style="width: 220px"
            @input="onFilterChange"
          />
          <el-select
            v-model="riskFilter"
            placeholder="风险等级"
            clearable
            style="width: 130px"
            @change="onFilterChange"
          >
            <el-option label="High" value="High" />
            <el-option label="Medium" value="Medium" />
            <el-option label="Low" value="Low" />
          </el-select>
          <el-select
            v-model="categoryFilter"
            placeholder="分类"
            clearable
            style="width: 150px"
            @change="onFilterChange"
          >
            <el-option
              v-for="cat in categories"
              :key="cat"
              :label="cat"
              :value="cat"
            />
          </el-select>
        </div>

        <el-table
          :data="pagedIssues"
          stripe
          @row-click="openIssue"
          style="cursor: pointer; margin-top: 12px"
        >
          <el-table-column label="" width="40">
            <template #default="{ row }">
              <el-tag
                :type="
                  row.risk_level === 'High'
                    ? 'danger'
                    : row.risk_level === 'Medium'
                      ? 'warning'
                      : 'success'
                "
                size="small"
              >
                {{
                  row.risk_level === 'High'
                    ? 'H'
                    : row.risk_level === 'Medium'
                      ? 'M'
                      : 'L'
                }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="title"
            label="标题"
            min-width="220"
            show-overflow-tooltip
          />
          <el-table-column prop="category" label="分类" width="110" />
          <el-table-column
            prop="issue_type"
            label="类型"
            width="150"
            show-overflow-tooltip
          />
          <el-table-column label="文件" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.relative_path }} :{{ row.start_line }}
            </template>
          </el-table-column>
          <el-table-column prop="critic_decision" label="Critic" width="90" />
          <el-table-column label="置信度" width="90">
            <template #default="{ row }">
              {{ (row.confidence * 100).toFixed(0) }}%
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag
                v-if="row.status !== 'open'"
                :type="
                  row.status === 'confirmed'
                    ? 'success'
                    : row.status === 'false_positive'
                      ? 'danger'
                      : 'warning'
                "
                size="small"
              >
                {{
                  row.status === 'confirmed'
                    ? '已确认'
                    : row.status === 'false_positive'
                      ? '误报'
                      : '待复核'
                }}
              </el-tag>
              <span v-else style="color: var(--muted); font-size: 12px">—</span>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-if="filteredIssues.length > pageSize"
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredIssues.length"
          :page-sizes="[10, 15, 25, 50]"
          layout="total, sizes, prev, pager, next"
          style="margin-top: 16px; justify-content: flex-end"
          size="small"
        />
      </section>

      <!-- Degradation summary -->
      <section
        v-if="Object.keys(report.degradation_summary).length"
        class="report-section"
      >
        <h2>降级记录</h2>
        <ul>
          <li v-for="(v, k) in report.degradation_summary" :key="k">
            <strong>{{ k }}</strong
            >: {{ v }}
          </li>
        </ul>
      </section>
    </template>

    <!-- Empty state -->
    <template v-else-if="!loading">
      <div style="text-align: center; padding: 48px 0">
        <p style="color: var(--muted)">报告加载失败或任务不存在。</p>
        <el-button type="primary" @click="loadData()"> 重新加载 </el-button>
      </div>
    </template>

    <IssueDetailDrawer
      v-model:visible="drawerVisible"
      :issue="selectedIssue"
      :task-id="taskId"
    />
  </div>
</template>

<style scoped>
.report-header {
  margin-bottom: 24px;
}
.report-header h1 {
  font-size: 24px;
  margin-bottom: 4px;
}

.filter-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
</style>
