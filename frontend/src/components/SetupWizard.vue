<script setup lang="ts">
import { NAlert, NButton, NCard, NInput, NProgress, NRadioButton, NRadioGroup, NSpace, useMessage } from 'naive-ui'
import { onBeforeUnmount, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits<{ (e: 'done'): void }>()
const message = useMessage()
const tier = ref('8gb')
const mirror = ref('')
const task = ref<any>(null)
let timer: number | undefined

async function start() {
  await api('/settings', { method: 'PUT', body: JSON.stringify({ values: { memory_tier: tier.value, hf_mirror: mirror.value } }) })
  task.value = await api('/models/setup', { method: 'POST' })
  const tick = async () => {
    task.value = await api(`/tasks/${task.value.id}`)
    if (task.value.status === 'running') timer = window.setTimeout(tick, 1000)
    else if (task.value.status === 'error') message.error(task.value.error)
    else emit('done')
  }
  tick()
}
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <n-card title="首次使用：准备本地模型" id="setup-wizard">
    <n-space vertical>
      <div>PaperMind 在你的电脑上运行小型语言模型和嵌入模型，<b>不需要任何 API key</b>，数据不出本机。首次需要下载模型（约 1–6 GB，只下载一次）。</div>
      <n-space align="center">选择内存档位：
        <n-radio-group v-model:value="tier">
          <n-radio-button value="8gb">8 GB 内存（轻量，约 2.2 GB 下载）</n-radio-button>
          <n-radio-button value="16gb">16 GB 内存（高质量，约 6.3 GB 下载）</n-radio-button>
        </n-radio-group>
      </n-space>
      <n-space align="center">下载镜像（国内网络可填）：<n-input v-model:value="mirror" placeholder="如 https://hf-mirror.com，留空使用官方" style="width: 320px" /></n-space>
      <n-space>
        <n-button type="primary" :loading="task?.status === 'running'" @click="start" id="wizard-start">开始准备</n-button>
        <span style="color: #888">也可以先跳过：规则解析、关键词搜索、论文库浏览不需要模型。</span>
      </n-space>
      <template v-if="task">
        <n-progress type="line" :percentage="Math.round(task.progress * 100)" :status="task.status === 'error' ? 'error' : 'default'" />
        <div style="color: #888">{{ task.message }}</div>
        <n-alert v-if="task.status === 'error'" type="error">{{ task.error }}（可在设置页手动指定 llama-server 路径，或换镜像后重试）</n-alert>
      </template>
    </n-space>
  </n-card>
</template>
