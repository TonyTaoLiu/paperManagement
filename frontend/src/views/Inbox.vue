<script setup lang="ts">
import { NAlert, NButton, NCard, NEmpty, NInput, NProgress, NSpace, NTag, useMessage } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const message = useMessage()
const items = ref<any[]>([])
const task = ref<any>(null)
const newName = ref<Record<number, string>>({})

async function load() {
  items.value = await api('/inbox')
}
async function confirm(pid: number, cid: number) {
  await api(`/inbox/${pid}/decision`, { method: 'POST', body: JSON.stringify({ action: 'confirm', category_id: cid }) })
  items.value = items.value.filter((i) => i.id !== pid)
}
async function reject(pid: number, cid: number) {
  const r = await api(`/inbox/${pid}/decision`, { method: 'POST', body: JSON.stringify({ action: 'reject', category_id: cid }) })
  const it = items.value.find((i) => i.id === pid)
  if (it && r.suggestions) it.suggestions = r.suggestions
}
async function createNew(pid: number) {
  const name = (newName.value[pid] || '').trim()
  if (!name) return
  await api(`/inbox/${pid}/decision`, { method: 'POST', body: JSON.stringify({ action: 'new', new_name: name }) })
  items.value = items.value.filter((i) => i.id !== pid)
}
async function runClassify() {
  task.value = await api('/classify', { method: 'POST', body: JSON.stringify({}) })
  const tick = async () => {
    task.value = await api(`/tasks/${task.value.id}`)
    if (task.value.status === 'running') setTimeout(tick, 800)
    else if (task.value.status === 'error') message.error(task.value.error)
    else await load()
  }
  tick()
}
onMounted(load)
</script>

<template>
  <n-space vertical>
    <n-card title="待确认分类">
      <n-space align="center">
        <n-button type="primary" @click="runClassify" id="classify-btn">自动分类所有未分类论文</n-button>
        <span style="color: #888">低置信度的论文会出现在这里，点一下建议类别即可确认。</span>
      </n-space>
      <n-progress v-if="task && task.status === 'running'" type="line" :percentage="Math.round(task.progress * 100)" style="margin-top: 8px" />
      <n-alert v-if="task && task.status === 'done'" type="success" style="margin-top: 8px">
        完成：自动归类 {{ task.result.auto }} 篇，待确认 {{ task.result.inbox }} 篇，建议新建 {{ task.result.new }} 篇（{{ task.result.used_llm ? '使用了 LLM' : '仅用向量' }}）。
      </n-alert>
    </n-card>
    <n-empty v-if="!items.length" description="收件箱是空的" />
    <n-card v-for="it in items" :key="it.id" size="small" class="inbox-item">
      <div style="font-weight: 600; cursor: pointer" @click="router.push(`/paper/${it.id}`)">{{ it.title }}</div>
      <div v-if="it.one_liner" style="color: #555; margin: 4px 0">{{ it.one_liner }}</div>
      <div style="color: #888; margin-bottom: 6px">{{ it.reason }}（点击类别 = 确认归入）</div>
      <n-space align="center">
        <n-space v-for="s in it.suggestions" :key="s.category_id" size="small" align="center">
          <n-button size="small" type="primary" secondary @click="confirm(it.id, s.category_id)">{{ s.name }} · {{ Math.round(s.score * 100) }}%</n-button>
          <n-button size="tiny" quaternary @click="reject(it.id, s.category_id)">✕</n-button>
        </n-space>
        <n-input v-model:value="newName[it.id]" size="small" placeholder="或输入新类别名" style="width: 160px" @keyup.enter="createNew(it.id)" />
        <n-button size="small" @click="createNew(it.id)" :disabled="!(newName[it.id] || '').trim()">新建并归入</n-button>
      </n-space>
    </n-card>
  </n-space>
</template>
