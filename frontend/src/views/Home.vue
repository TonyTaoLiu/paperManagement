<script setup lang="ts">
import { NAlert, NCard, NSpace } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { api } from '../api'

const health = ref<any>(null)
const error = ref('')
onMounted(async () => {
  try {
    health.value = await api('/health')
  } catch (e: any) {
    error.value = String(e)
  }
})
</script>

<template>
  <n-space vertical>
    <n-card title="欢迎使用 PaperMind">
      论文记忆库：导入 ChatGPT 论文总结，自动分类、建立知识图谱、推荐新论文。
    </n-card>
    <n-alert v-if="error" type="error">后端连接失败：{{ error }}</n-alert>
    <n-card v-else-if="health" title="运行状态" id="health-card">
      版本 {{ health.version }} · 平台 {{ health.platform }} · 全文检索(FTS5)：{{ health.fts5 ? '可用' : '不可用' }}
      <div style="color: #888; margin-top: 4px">数据目录：{{ health.data_dir }}</div>
    </n-card>
  </n-space>
</template>
