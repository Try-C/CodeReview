<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="page-container" style="text-align: center">
    <p class="eyebrow">404</p>
    <h1>页面未找到</h1>
    <p style="color: var(--muted); margin: 16px 0 24px">
      你访问的页面不存在或已被移除。
    </p>
    <el-button type="primary" @click="router.push({ name: 'home' })">
      返回首页
    </el-button>
  </div>
</template>
