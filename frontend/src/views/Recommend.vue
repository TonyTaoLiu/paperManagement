<script setup lang="ts">
import { NAlert, NButton, NCard, NEmpty, NInput, NProgress, NSpace, NTabPane, NTabs, NTag, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const message = useMessage()
const group = ref('')
const items = ref<any[]>([])
const task = ref<any>(null)
const authors = ref<any[]>([])
const newAuthor = ref('')
const groups = [
  { name: '', label: '全部' },
  { name: 'new', label: '每日新论文' },
  { name: 'classic', label: '经典缺失' },
  { name: 'team', label: '团队动态' },
  { name: 'topic', label: '按主题' },
  { name: 'liked', label: '已收藏' },
]
const status = computed(() => (group.value === 'liked' ? 'liked' : 'new'))

async function load() {
  const p = new URLSearchParams({ status: status.value })
  if (group.value && group.value !== 'liked') p.set('group', group.value)
  items.value = await api(`/recommendations?${p}`)
  authors.value = await api('/authors?followed=true')
}
async function refresh() {
  task.value = await api('/recommendations/refresh', { method: 'POST' })
  const tick = async () => {
    task.value = await api(`/tasks/${task.value.id}`)
    if (task.value.status === 'running') setTimeout(tick, 1500)
    else if (task.value.status === 'error') message.error(task.value.error)
    else await load()
  }
  tick()
}
async function feedback(it: any, value: number) {
  await api(`/recommendations/${it.id}/feedback`, { method: 'POST', body: JSON.stringify({ value }) })
  await load()
}
async function copyTask(it: any) {
  const r = await api(`/prompt?paper_url=${encodeURIComponent(it.url || it.title)}`)
  await navigator.clipboard.writeText(r.prompt)
  message.success('已复制：粘贴到 ChatGPT，读完后把聊天记录导回来')
}
async function follow() {
  if (!newAuthor.value.trim()) return
  await api('/authors', { method: 'POST', body: JSON.stringify({ name: newAuthor.value }) })
  newAuthor.value = ''
  await load()
}
async function unfollow(a: any) {
  await api(`/authors/${a.id}/follow?value=false`, { method: 'POST' })
  await load()
}
onMounted(load)
</script>

<template>
  <n-space vertical>
    <n-card title="论文推荐">
      <n-space align="center">
        <n-button type="primary" @click="refresh" :loading="task?.status === 'running'" id="refresh-btn">立即获取推荐</n-button>
        <span style="color: #888">来源：OpenAlex / arXiv / bioRxiv / medRxiv / PubMed / Semantic Scholar；每天早 8 点自动刷新（需应用在运行）。</span>
      </n-space>
      <n-progress v-if="task?.status === 'running'" type="line" :percentage="Math.round(task.progress * 100)" style="margin-top: 8px" />
      <div v-if="task?.status === 'running'" style="color: #888">{{ task.message }}</div>
      <n-alert v-if="task?.status === 'done'" type="success" style="margin-top: 8px">获取 {{ task.result.fetched }} 篇，新增 {{ task.result.stored }} 篇，已排序 {{ task.result.ranked }} 篇。</n-alert>
      <div style="margin-top: 12px">
        <span style="color: #888; margin-right: 8px">关注的作者/团队：</span>
        <n-tag v-for="a in authors" :key="a.id" closable size="small" style="margin-right: 4px" @close="unfollow(a)">{{ a.name }}</n-tag>
        <n-input v-model:value="newAuthor" size="small" placeholder="添加作者姓名" style="width: 180px" @keyup.enter="follow" />
        <n-button size="small" @click="follow" style="margin-left: 4px">关注</n-button>
      </div>
    </n-card>
    <n-tabs v-model:value="group" type="line" @update:value="load">
      <n-tab-pane v-for="g in groups" :key="g.name" :name="g.name" :tab="g.label" />
    </n-tabs>
    <n-empty v-if="!items.length" description="暂无推荐。点击「立即获取推荐」（需要已下载嵌入模型）。" />
    <n-card v-for="it in items" :key="it.id" size="small" class="rec-item">
      <div style="font-weight: 600"><a :href="it.url" target="_blank" rel="noopener">{{ it.title }}</a></div>
      <div style="color: #888; font-size: 12px">{{ it.authors.slice(0, 4).join(', ') }} · {{ it.venue }} {{ it.year }} · {{ it.source }}</div>
      <div style="margin: 6px 0; color: #2a6e4b">💡 {{ it.reason }}</div>
      <div style="color: #555; max-height: 4.5em; overflow: hidden">{{ it.abstract }}</div>
      <n-space style="margin-top: 8px" size="small">
        <n-button size="tiny" @click="feedback(it, 1)">👍 感兴趣</n-button>
        <n-button size="tiny" @click="feedback(it, -1)">👎 不相关</n-button>
        <n-button size="tiny" @click="feedback(it, 0)">已读</n-button>
        <n-button size="tiny" tertiary @click="copyTask(it)">复制 ChatGPT 总结任务</n-button>
        <n-tag size="tiny">{{ it.score?.toFixed(2) }}</n-tag>
      </n-space>
    </n-card>
  </n-space>
</template>
