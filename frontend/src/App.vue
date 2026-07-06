<script setup lang="ts">
import { RouterView, useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a
        class="brand"
        href="/"
        aria-label="CodeReview Agent 首页"
        @click.prevent="goHome"
      >
        <span class="brand-mark" aria-hidden="true">&lt;/&gt;</span>
        <span>
          <strong>CodeReview Agent</strong>
          <small>Evidence-grounded review</small>
        </span>
      </a>

      <el-tag effect="plain" type="success" size="small">P0</el-tag>
    </header>

    <main class="main-content">
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>
