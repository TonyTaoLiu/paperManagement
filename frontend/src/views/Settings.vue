<script setup lang="ts">
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NInputNumber, NProgress, NRadioButton, NRadioGroup, NSpace, NSwitch, NTag, useMessage } from 'naive-ui'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'

const message = useMessage()
const s = ref<any>(null)
const status = ref<any>(null)
const task = ref<any>(null)
const prompt = ref('')
const backups = ref<any[]>([])
let timer: number | undefined

async function loadAll() {
  s.value = await api('/settings')
  status.value = await api('/models/status')
  backups.value = await api('/backups')
}
async function save() {
  s.value = await api('/settings', { method: 'PUT', body: JSON.stringify({ values: s.value }) })
  status.value = await api('/models/status')
  message.success('已保存')
}
async function setup() {
  await save()
  task.value = await api('/models/setup', { method: 'POST' })
  const tick = async () => {
    task.value = await api(`/tasks/${task.value.id}`)
    if (task.value.status === 'running') timer = window.setTimeout(tick, 1000)
    else {
      if (task.value.status === 'error') message.error(task.value.error)
      status.value = await api('/models/status')
    }
  }
  tick()
}
async function showPrompt() {
  prompt.value = (await api('/prompt')).prompt
}
async function copyPrompt() {
  await navigator.clipboard.writeText(prompt.value)
  message.success('已复制')
}
async function backupNow() {
  await api('/backups', { method: 'POST' })
  backups.value = await api('/backups')
  message.success('已备份')
}
onMounted(loadAll)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <n-space vertical v-if="s">
    <n-card title="本地模型（无需 API key）">
      <n-form label-placement="left" label-width="140" style="max-width: 680px">
        <n-form-item label="内存档位">
          <n-radio-group v-model:value="s.memory_tier" @update:value="save">
            <n-radio-button value="8gb">8 GB（轻量）</n-radio-button>
            <n-radio-button value="16gb">16 GB（高质量）</n-radio-button>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="状态" v-if="status">
          <n-space vertical size="small">
            <div>llama-server：<n-tag size="small" :type="status.llama_server ? 'success' : 'warning'">{{ status.llama_server ? '已就绪' : '未获取' }}</n-tag></div>
            <div>生成模型 {{ status.llm.id }}（{{ status.llm.size_gb }} GB）：<n-tag size="small" :type="status.llm.downloaded ? 'success' : 'warning'">{{ status.llm.downloaded ? '已下载' : '未下载' }}</n-tag></div>
            <div>嵌入模型 {{ status.embed.id }}（{{ status.embed.size_gb }} GB）：<n-tag size="small" :type="status.embed.downloaded ? 'success' : 'warning'">{{ status.embed.downloaded ? '已下载' : '未下载' }}</n-tag></div>
          </n-space>
        </n-form-item>
        <n-form-item label="HF 镜像地址"><n-input v-model:value="s.hf_mirror" placeholder="如 https://hf-mirror.com，留空使用官方" /></n-form-item>
        <n-form-item label="llama-server 路径"><n-input v-model:value="s.llama_server_path" placeholder="留空则自动下载或编译" /></n-form-item>
        <n-form-item label="外部端点"><n-input v-model:value="s.external_endpoint" placeholder="已运行的 OpenAI 兼容端点，如 http://127.0.0.1:11434/v1 (Ollama)" /></n-form-item>
        <n-form-item><n-button type="primary" @click="setup" :loading="task?.status === 'running'" id="setup-btn">下载 / 准备模型</n-button></n-form-item>
      </n-form>
      <n-progress v-if="task" type="line" :percentage="Math.round(task.progress * 100)" :status="task.status === 'error' ? 'error' : task.status === 'done' ? 'success' : 'default'" />
      <div v-if="task" style="color: #888">{{ task.message }}</div>
      <n-alert v-if="task?.status === 'error'" type="error" style="margin-top: 8px">{{ task.error }}</n-alert>
    </n-card>

    <n-card title="云端 LLM（可选增强）">
      <n-form label-placement="left" label-width="140" style="max-width: 680px">
        <n-form-item label="启用云端 LLM"><n-switch v-model:value="s.cloud_llm.enabled" /></n-form-item>
        <template v-if="s.cloud_llm.enabled">
          <n-form-item label="Base URL"><n-input v-model:value="s.cloud_llm.base_url" placeholder="如 https://api.deepseek.com/v1" /></n-form-item>
          <n-form-item label="API Key"><n-input v-model:value="s.cloud_llm.api_key" type="password" show-password-on="click" /></n-form-item>
          <n-form-item label="模型名"><n-input v-model:value="s.cloud_llm.model" /></n-form-item>
          <n-alert type="warning" :show-icon="false">启用后，论文笔记内容会发送到你配置的云端服务；嵌入始终在本地进行。</n-alert>
        </template>
      </n-form>
    </n-card>

    <n-card title="元数据与推荐">
      <n-form label-placement="left" label-width="180" style="max-width: 680px">
        <n-form-item label="导入后补全元数据"><n-switch v-model:value="s.enrich_metadata" /></n-form-item>
        <n-form-item label="联系邮箱（可选）"><n-input v-model:value="s.contact_email" placeholder="发给 OpenAlex 的礼貌池标识，不填也可" /></n-form-item>
        <n-form-item label="OpenAlex API Key（可选）"><n-input v-model:value="s.openalex_api_key" type="password" show-password-on="click" placeholder="共享网络出口被限流时填写，免费申请" /></n-form-item>
        <n-form-item label="Semantic Scholar Key（可选）"><n-input v-model:value="s.s2_api_key" type="password" show-password-on="click" /></n-form-item>
        <n-form-item label="每日自动推荐"><n-switch v-model:value="s.rec_daily" /> <span style="margin: 0 8px">每天</span> <n-input-number v-model:value="s.rec_hour" :min="0" :max="23" style="width: 90px" /> <span style="margin-left: 8px">点（重启后生效）</span></n-form-item>
      </n-form>
      <n-button type="primary" @click="save" id="save-btn">保存设置</n-button>
    </n-card>

    <n-card title="总结 Prompt 与备份">
      <n-space vertical>
        <n-space>
          <n-button @click="showPrompt">查看改进版总结 Prompt</n-button>
          <n-button v-if="prompt" @click="copyPrompt">复制</n-button>
          <n-button @click="backupNow">立即备份数据库</n-button>
          <a href="/api/export?format=json">导出 JSON 全量备份</a>
          <a href="/api/export?format=obsidian">导出 Obsidian 库</a>
          <a href="/api/export?format=md">导出 Markdown</a>
          <a href="/api/export?format=bibtex">导出 BibTeX</a>
        </n-space>
        <pre v-if="prompt" style="white-space: pre-wrap; background: #f7f7f7; padding: 8px; max-height: 280px; overflow: auto">{{ prompt }}</pre>
        <div v-if="backups.length" style="color: #888">最近备份：{{ backups.slice(0, 3).map((b) => b.name).join('，') }}</div>
        <div style="color: #888">数据目录：{{ status?.data_dir }}</div>
      </n-space>
    </n-card>
  </n-space>
</template>
