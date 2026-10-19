<script setup lang="ts">
import { NAlert, NButton, NCard, NInput, NSpace, NTag } from 'naive-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import Markdown from '../components/Markdown.vue'

const router = useRouter()
const q = ref('')
const answer = ref('')
const sources = ref<any[]>([])
const busy = ref(false)
const usedLlm = ref(true)
const examples = ['我读过的论文里，哪些对 beta 作为 aDBS 生物标志物提出了质疑？', 'Percept 上的 aDBS 能不能改算法？', '哪些论文用到了睡眠 PSG 数据？']

async function ask() {
  if (!q.value.trim()) return
  busy.value = true
  answer.value = ''
  sources.value = []
  const res = await fetch('/api/qa', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q.value, stream: true }) })
  const reader = res.body!.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue
      const ev = JSON.parse(part.slice(6))
      if (ev.delta) answer.value += ev.delta
      if (ev.done) {
        sources.value = ev.sources
        usedLlm.value = ev.used_llm
        if (ev.answer) answer.value = ev.answer
      }
    }
  }
  busy.value = false
}
// citations like [P12] -> markdown link
const rendered = () => answer.value.replace(/\[P(\d+)\]/g, '[P$1](#/paper/$1)')
</script>

<template>
  <n-space vertical>
    <n-card title="问我的论文库">
      <n-space vertical>
        <n-input v-model:value="q" type="textarea" :rows="2" placeholder="基于你已读论文的笔记提问；库里没有依据时会直说「库中没有相关内容」" id="qa-input" @keydown.ctrl.enter="ask" />
        <n-space>
          <n-button type="primary" :loading="busy" @click="ask" id="qa-btn">提问（Ctrl+Enter）</n-button>
          <n-button v-for="e in examples" :key="e" size="small" tertiary @click="(q = e), ask()">{{ e }}</n-button>
        </n-space>
      </n-space>
    </n-card>
    <n-card v-if="answer" title="回答">
      <Markdown :source="rendered()" id="qa-answer" />
      <n-alert v-if="!usedLlm && !busy" type="info" style="margin-top: 8px">未启用 LLM，这里只列出最相关的笔记片段。在设置页下载生成模型后可获得完整回答。</n-alert>
      <div v-if="sources.length" style="margin-top: 12px">
        <span style="color: #888">来源论文：</span>
        <n-tag v-for="s in sources" :key="s.id" size="small" style="margin-right: 6px; cursor: pointer" @click="router.push(`/paper/${s.id}`)">P{{ s.id }} {{ s.title.slice(0, 36) }}</n-tag>
      </div>
    </n-card>
  </n-space>
</template>
