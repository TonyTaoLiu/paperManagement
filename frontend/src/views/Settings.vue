<script setup lang="ts">
import { NButton, NCard, NForm, NFormItem, NInput, NRadioButton, NRadioGroup, NSwitch, useMessage } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { api } from '../api'

const message = useMessage()
const s = ref<any>(null)
onMounted(async () => (s.value = await api('/settings')))

async function save() {
  s.value = await api('/settings', { method: 'PUT', body: JSON.stringify({ values: s.value }) })
  message.success('已保存')
}
</script>

<template>
  <n-card title="设置" v-if="s">
    <n-form label-placement="left" label-width="140" style="max-width: 640px">
      <n-form-item label="内存档位">
        <n-radio-group v-model:value="s.memory_tier">
          <n-radio-button value="8gb">8 GB（轻量）</n-radio-button>
          <n-radio-button value="16gb">16 GB（高质量）</n-radio-button>
        </n-radio-group>
      </n-form-item>
      <n-form-item label="HF 镜像地址"><n-input v-model:value="s.hf_mirror" placeholder="如 https://hf-mirror.com，留空使用官方" /></n-form-item>
      <n-form-item label="llama-server 路径"><n-input v-model:value="s.llama_server_path" placeholder="留空则自动获取" /></n-form-item>
      <n-form-item label="外部端点"><n-input v-model:value="s.external_endpoint" placeholder="如 http://127.0.0.1:11434/v1 (Ollama)" /></n-form-item>
      <n-form-item label="启用云端 LLM"><n-switch v-model:value="s.cloud_llm.enabled" /></n-form-item>
      <template v-if="s.cloud_llm.enabled">
        <n-form-item label="Base URL"><n-input v-model:value="s.cloud_llm.base_url" /></n-form-item>
        <n-form-item label="API Key"><n-input v-model:value="s.cloud_llm.api_key" type="password" show-password-on="click" /></n-form-item>
        <n-form-item label="模型名"><n-input v-model:value="s.cloud_llm.model" /></n-form-item>
        <n-form-item><span style="color:#c60">启用后，论文内容会发送到你配置的云端服务。</span></n-form-item>
      </template>
      <n-button type="primary" @click="save">保存</n-button>
    </n-form>
  </n-card>
</template>
