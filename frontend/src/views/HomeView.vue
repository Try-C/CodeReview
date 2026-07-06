<script setup lang="ts">
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElSkeleton,
  ElTag,
} from "element-plus";
import { computed, onMounted } from "vue";

import { useHealthStore } from "@/stores/health";

const healthStore = useHealthStore();

const statusType = computed(() => {
  if (healthStore.phase === "ready") return "success";
  if (healthStore.phase === "error") return "danger";
  return "info";
});

const statusLabel = computed(() => {
  const labels = {
    idle: "等待检查",
    loading: "检查中",
    ready: "API 已就绪",
    error: "API 不可用",
  };
  return labels[healthStore.phase];
});

const checkedAt = computed(() => {
  if (!healthStore.lastCheckedAt) return "尚未检查";
  return healthStore.lastCheckedAt.toLocaleTimeString("zh-CN", {
    hour12: false,
  });
});

onMounted(() => {
  void healthStore.refresh();
});
</script>

<template>
  <section class="hero">
    <div class="hero-copy">
      <p class="eyebrow">AI CODE REVIEW PLATFORM</p>
      <h1>让每一条审查结论<br />都能回到真实代码。</h1>
      <p class="hero-description">
        通过语义解析、Hybrid RAG、确定性证据校验和有界 Agent
        工作流，生成可定位、可追溯、可评测的代码审查报告。
      </p>

      <div class="principles" aria-label="项目核心原则">
        <span>真实证据</span>
        <span>有界执行</span>
        <span>量化评测</span>
      </div>
    </div>

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
        <ElDescriptionsItem label="配置检查">
          <ElTag
            :type="
              healthStore.readiness.checks.configuration === 'ok'
                ? 'success'
                : 'danger'
            "
            effect="plain"
            size="small"
          >
            {{ healthStore.readiness.checks.configuration ?? "unknown" }}
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
        <p>PostgreSQL 全文检索与千问向量通过 RRF 融合。</p>
      </article>
      <article>
        <span>03</span>
        <h3>Verify</h3>
        <p>确定性节点验证证据归属，再交由 Critic 语义复核。</p>
      </article>
      <article>
        <span>04</span>
        <h3>Measure</h3>
        <p>记录 Precision、Recall、耗时、Token 与真实成本。</p>
      </article>
    </div>
  </section>
</template>
