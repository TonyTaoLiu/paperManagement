<script setup lang="ts">
import { NAlert, NButton, NCard, NSpace, NTag, useMessage } from 'naive-ui'
import { onMounted, ref } from 'vue'
import Markdown from '../components/Markdown.vue'
import { api } from '../api'

const message = useMessage()
const cats = ref<any[]>([])
const digest = ref<any>(null)
const current = ref<any>(null)
const proposal = ref<any>(null)
const health = ref<string[]>([])
const busy = ref(false)

async function loadCats() {
  const tree = await api('/categories')
  const out: any[] = []
  const walk = (ns: any[], d: number) => ns.forEach((n) => (out.push({ ...n, depth: d }), walk(n.children, d + 1)))
  walk(tree, 0)
  cats.value = out
}
async function open(c: any) {
  current.value = c
  proposal.value = null
  try {
    digest.value = await api(`/digests/${c.id}`)
    health.value = (await api(`/digests/${c.id}/health`)).issues
  } catch {
    digest.value = null
    health.value = []
  }
}
async function propose() {
  busy.value = true
  try {
    proposal.value = await api(`/digests/${current.value.id}/propose`, { method: 'POST' })
  } finally {
    busy.value = false
  }
}
async function accept() {
  digest.value = await api(`/digests/${current.value.id}/accept`, { method: 'POST', body: JSON.stringify({ content_md: proposal.value.content_md, source_paper_ids: proposal.value.source_paper_ids }) })
  proposal.value = null
  message.success('综述已更新')
  health.value = (await api(`/digests/${current.value.id}/health`)).issues
}
onMounted(loadCats)
</script>

<template>
  <div style="display: flex; gap: 16px">
    <n-card title="主题" size="small" style="width: 280px; flex: none">
      <div v-for="c in cats" :key="c.id" :style="{ paddingLeft: c.depth * 14 + 'px', cursor: 'pointer', margin: '4px 0', fontWeight: current?.id === c.id ? 600 : 400 }" class="digest-cat" @click="open(c)">
        {{ c.name }} <n-tag size="tiny">{{ c.n_papers }}</n-tag>
      </div>
      <div v-if="!cats.length" style="color: #888">请先建立分类体系并分类论文。</div>
    </n-card>
    <n-space vertical style="flex: 1">
      <n-card v-if="current" :title="`${current.name} · 综述`">
        <template #header-extra>
          <n-space align="center">
            <n-tag v-if="digest?.stale" type="warning" size="small">有新论文，建议更新</n-tag>
            <span v-if="digest" style="color: #888">v{{ digest.version }} · {{ digest.updated_at }}</span>
            <n-button size="small" :loading="busy" @click="propose">重新生成（先预览差异）</n-button>
          </n-space>
        </template>
        <Markdown v-if="digest?.content_md" :source="digest.content_md" id="digest-body" />
        <div v-if="digest && !digest.content_md" style="color: #888">这个主题下还没有论文。</div>
      </n-card>
      <n-alert v-if="health.length" type="warning" title="健康检查">
        <div v-for="h in health" :key="h">· {{ h }}</div>
      </n-alert>
      <n-card v-if="proposal" title="新版本预览" size="small">
        <n-tag size="small">{{ proposal.used_llm ? '由 LLM 生成' : '规则生成（未使用 LLM）' }}</n-tag>
        <pre v-if="proposal.diff" style="background: #f7f7f7; padding: 8px; overflow: auto; font-size: 12px">{{ proposal.diff }}</pre>
        <Markdown :source="proposal.content_md" />
        <n-space><n-button type="primary" size="small" @click="accept">采用新版</n-button><n-button size="small" @click="proposal = null">放弃</n-button></n-space>
      </n-card>
    </n-space>
  </div>
</template>
