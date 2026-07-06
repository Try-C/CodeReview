<script setup lang="ts">
/** Step 02: folder selection with file stats. */
import { ElCard } from 'element-plus'
import { computed } from 'vue'
import type { ProjectFileSelection } from '@/types/workflow'

const props = defineProps<{
  selectedFiles: ProjectFileSelection[]
  projectName: string
}>()

const emit = defineEmits<{
  select: [files: ProjectFileSelection[], projectName: string]
}>()

const SUPPORTED_EXTENSIONS = ['.py', '.java']

const supportedFileCount = computed(
  () =>
    props.selectedFiles.filter(({ relativePath }) =>
      SUPPORTED_EXTENSIONS.some((ext) => relativePath.endsWith(ext)),
    ).length,
)

function onFolderChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (files.length === 0) {
    emit('select', [], '')
    return
  }

  const normalizedPaths = files.map((file) =>
    (file.webkitRelativePath || file.name).replaceAll('\\', '/'),
  )
  const firstParts = normalizedPaths[0]?.split('/') ?? []
  const rootFolder = firstParts.length > 1 ? firstParts[0] : ''
  const name = rootFolder || props.projectName || 'local-project'
  const mapped = files.map((file, index) => {
    const path = normalizedPaths[index] ?? file.name
    return {
      file,
      relativePath:
        rootFolder && path.startsWith(`${rootFolder}/`)
          ? path.slice(rootFolder.length + 1)
          : path,
    }
  })
  emit('select', mapped, name)
}
</script>

<template>
  <el-card class="workflow-card" shadow="never">
    <template #header>
      <div class="step-title">
        <span>02</span>
        <strong>选择项目文件夹</strong>
      </div>
    </template>

    <label class="folder-picker">
      <input
        type="file"
        webkitdirectory
        directory
        multiple
        @change="onFolderChange"
      />
      <span>选择本地文件夹</span>
      <small>只会处理后端允许的 Java/Python 文本源码</small>
    </label>

    <div v-if="selectedFiles.length" class="selection-summary">
      <strong>{{ projectName }}</strong>
      <span>
        共 {{ selectedFiles.length }} 个文件，检测到 {{ supportedFileCount }} 个
        Java/Python 文件
      </span>
    </div>
  </el-card>
</template>
