<script setup lang="ts">
import { NAlert, NButton, NCard, NCheckbox, NDataTable, NInput, NProgress, NSpace, NStatistic, NTabPane, NTabs, NUpload, useMessage } from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const message = useMessage()
const router = useRouter()
const text = ref('')
const useLlm = ref(true)
const task = ref<any>(null)
let timer: number | undefined

async function poll(id: string) {
  task.value = await api(`/import/${id}`)
  if (task.value.status === 'running') timer = window.setTimeout(() => poll(id), 800)
  else if (task.value.status === 'error') message.error(task.value.error)
}
async function submitText() {
  task.value = await api('/import/text', { method: 'POST', body: JSON.stringify({ text: text.value, use_llm: useLlm.value }) })
  poll(task.value.id)
}
async function onUpload(opts: { file: UploadFileInfo }) {
  const fd = new FormData()
  fd.append('file', opts.file.file as File)
  fd.append('use_llm', String(useLlm.value))
  const res = await fetch('/api/import/file', { method: 'POST', body: fd })
  task.value = await res.json()
  poll(task.value.id)
}
onBeforeUnmount(() => clearTimeout(timer))
const columns = [
  { title: '论文', key: 'title' },
  { title: '处理结果', key: 'action', render: (r: any) => (r.action === 'new' ? '新增' : '合并'), width: 90 },
  { title: '追问', key: 'followups', width: 70 },
  { title: '对话轮次', key: 'turns', render: (r: any) => r.turns.join(', '), width: 140 },
]
</script>

<template>
  <n-space vertical>
    <n-card title="导入聊天记录">
      <n-tabs type="line">
        <n-tab-pane name="file" tab="上传文件">
          <p>支持：归档 Markdown（如 <code>论文总结记录.md</code>）、ChatGPT 官方导出的 <code>conversations.json</code>。重复导入不会产生重复记录。</p>
          <n-upload :custom-request="({ file }) => onUpload({ file })" :show-file-list="false" accept=".md,.json,.txt">
            <n-button type="primary" id="upload-btn">选择文件</n-button>
          </n-upload>
        </n-tab-pane>
        <n-tab-pane name="paste" tab="粘贴文本">
          <n-input v-model:value="text" type="textarea" :rows="10" placeholder="粘贴一篇论文的总结，或带“用户：/助手：”的对话文本" />
          <n-button type="primary" style="margin-top: 8px" :disabled="!text.trim()" @click="submitText">导入</n-button>
        </n-tab-pane>
      </n-tabs>
      <n-checkbox v-model:checked="useLlm" style="margin-top: 12px">使用 LLM 精修抽取（本地模型已就绪或已配置云端时生效；否则用规则抽取）</n-checkbox>
    </n-card>

    <n-card v-if="task" title="导入进度">
      <n-progress type="line" :percentage="Math.round(task.progress * 100)" :status="task.status === 'error' ? 'error' : task.status === 'done' ? 'success' : 'default'" />
      <div style="color: #888; margin-top: 4px">{{ task.message }}</div>
      <n-alert v-if="task.status === 'error'" type="error" style="margin-top: 8px">{{ task.error }}</n-alert>
      <template v-if="task.status === 'done' && task.result">
        <n-alert v-if="task.result.already_imported" type="info" style="margin-top: 8px">这份内容已经导入过，没有任何改动。</n-alert>
        <template v-else>
          <n-space style="margin: 12px 0" id="import-report">
            <n-statistic label="新增论文" :value="task.result.new" />
            <n-statistic label="合并" :value="task.result.merged" />
            <n-statistic label="追问" :value="task.result.followups" />
            <n-statistic label="非论文轮次" :value="task.result.non_paper.length" />
          </n-space>
          <n-data-table :columns="columns" :data="task.result.papers" size="small" :row-props="(r: any) => ({ style: 'cursor:pointer', onClick: () => router.push(`/paper/${r.id}`) })" />
        </template>
      </template>
    </n-card>
  </n-space>
</template>
