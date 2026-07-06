<script setup lang="ts">
import { ElTag } from 'element-plus'
import { RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="CodeReview Agent 首页">
        <span class="brand-mark" aria-hidden="true">&lt;/&gt;</span>
        <span>
          <strong>CodeReview Agent</strong>
          <small>Evidence-grounded review</small>
        </span>
      </RouterLink>

      <ElTag effect="plain" type="success">P0 · Module 12</ElTag>
    </header>

    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>
