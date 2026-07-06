<script setup lang="ts">
/** Step 01: auth panel — login / register / logout. */
import { ElButton, ElInput, ElMessage, ElTag } from 'element-plus'
import { ref } from 'vue'

import { clearAuth } from '@/api/client'
import { login, register } from '@/api/workflow'

const emit = defineEmits<{
  authenticated: []
  logout: []
}>()

const username = ref('')
const password = ref('')
const authenticating = ref(false)
const isAuthenticated = ref(Boolean(localStorage.getItem('access_token')))

async function doAuth(createAccount: boolean) {
  if (username.value.trim().length < 3 || password.value.length < 8) {
    ElMessage.warning('用户名至少 3 位，密码至少 8 位')
    return
  }

  authenticating.value = true
  try {
    if (createAccount) {
      await register(username.value.trim(), password.value)
    }
    const token = await login(username.value.trim(), password.value)
    localStorage.setItem('access_token', token.access_token)
    if (token.expires_in) {
      localStorage.setItem(
        'access_token_expires_at',
        String(Date.now() + token.expires_in * 1000),
      )
    }
    isAuthenticated.value = true
    password.value = ''
    ElMessage.success(createAccount ? '注册并登录成功' : '登录成功')
    emit('authenticated')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '认证失败')
  } finally {
    authenticating.value = false
  }
}

function doLogout() {
  clearAuth()
  isAuthenticated.value = false
  ElMessage.success('已退出登录')
  emit('logout')
}
</script>

<template>
  <el-card class="workflow-card" shadow="never">
    <template #header>
      <div class="step-title">
        <span>01</span>
        <strong>登录</strong>
        <el-tag v-if="isAuthenticated" type="success" size="small"
          >已登录</el-tag
        >
      </div>
    </template>

    <template v-if="!isAuthenticated">
      <el-input
        v-model="username"
        autocomplete="username"
        placeholder="用户名（至少 3 位）"
      />
      <el-input
        v-model="password"
        class="form-control"
        type="password"
        autocomplete="current-password"
        show-password
        placeholder="密码（至少 8 位）"
        @keyup.enter="doAuth(false)"
      />
      <div class="button-row">
        <el-button
          type="primary"
          :loading="authenticating"
          @click="doAuth(false)"
        >
          登录
        </el-button>
        <el-button :loading="authenticating" @click="doAuth(true)">
          注册并登录
        </el-button>
      </div>
    </template>
    <div v-else class="authenticated-row">
      <span>认证信息已保存在当前浏览器中。</span>
      <el-button text type="danger" @click="doLogout">退出</el-button>
    </div>
  </el-card>
</template>
