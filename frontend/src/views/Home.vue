<script setup lang="ts">
import { NAlert, NButton, NCard, NSpace, NStatistic } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import SetupWizard from '../components/SetupWizard.vue'
import { api } from '../api'

const router = useRouter()
const health = ref<any>(null)
const stats = ref<any>(null)
const status = ref<any>(null)
const error = ref('')
async function onMounted_() {
  status.value = await api('/models/status')
}
onMounted(async () => {
  try {
    health.value = await api('/health')
    stats.value = await api('/stats')
    status.value = await api('/models/status')
  } catch (e: any) {
    error.value = String(e)
  }
})
</script>

<template>
  <n-space vertical>
    <n-card title="欢迎使用 PaperMind">
      论文记忆库：导入 ChatGPT 论文总结，自动分类、建立知识图谱、推荐新论文。数据全部保存在本机。
    </n-card>
    <n-alert v-if="error" type="error">后端连接失败：{{ error }}</n-alert>
    <template v-else-if="health && stats">
      <n-card title="我的论文库" id="stats-card">
        <n-space size="large">
          <n-statistic label="论文" :value="stats.papers" />
          <n-statistic label="追问" :value="stats.followups" />
          <n-statistic label="待确认分类" :value="stats.inbox" />
          <n-statistic label="分类" :value="stats.categories" />
          <n-statistic label="实体" :value="stats.entities" />
          <n-statistic label="待复习" :value="stats.due_cards" />
        </n-space>
      </n-card>
      <SetupWizard v-if="status && (!status.embed.downloaded || !status.llama_server)" @done="onMounted_()" />
      <n-alert v-if="!stats.papers" type="info" title="从导入开始">
        <n-button size="small" type="primary" @click="router.push('/import')">导入聊天记录</n-button>
      </n-alert>
      <n-card title="运行状态" size="small" id="health-card">
        版本 {{ health.version }} · 平台 {{ health.platform }} · 全文检索(FTS5)：{{ health.fts5 ? '可用' : '不可用' }}
        <div style="color: #888; margin-top: 4px">数据目录：{{ health.data_dir }}</div>
      </n-card>
    </template>
  </n-space>
</template>
