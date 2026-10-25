<script setup lang="ts">
import { NCard, NEmpty, NInput, NPagination, NRadioButton, NRadioGroup, NSelect, NSpace, NTag } from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import VerifyBadge from '../components/VerifyBadge.vue'

const router = useRouter()
const items = ref<any[]>([])
const total = ref(0)
const q = ref('')
const mode = ref('hybrid')
const paperType = ref<string | null>(null)
const verification = ref<string | null>(null)
const page = ref(1)
const pageSize = 20
const types = ['原始研究', '综述', '数据资源', '计算模型', '方法与工具', '临床试验', '技术报告'].map((v) => ({ label: v, value: v }))
const verifs = ['全文已读', '部分章节', '仅摘要', '无法访问', '未核实'].map((v) => ({ label: v, value: v }))

async function load() {
  const p = new URLSearchParams({ limit: String(pageSize), offset: String((page.value - 1) * pageSize), mode: mode.value })
  if (q.value.trim()) p.set('q', q.value.trim())
  if (paperType.value) p.set('paper_type', paperType.value)
  if (verification.value) p.set('verification', verification.value)
  const r = await api(`/papers?${p}`)
  items.value = r.items
  total.value = r.total
}
let t: number | undefined
watch([q, mode, paperType, verification], () => {
  page.value = 1
  clearTimeout(t)
  t = window.setTimeout(load, 250)
})
watch(page, load)
onMounted(load)
</script>

<template>
  <n-space vertical>
    <n-card>
      <n-space align="center">
        <n-input v-model:value="q" placeholder="搜索标题、结论、总结内容…" clearable style="width: 360px" id="search-box" />
        <n-radio-group v-model:value="mode" size="small">
          <n-radio-button value="hybrid">混合</n-radio-button>
          <n-radio-button value="keyword">关键词</n-radio-button>
          <n-radio-button value="semantic">语义</n-radio-button>
        </n-radio-group>
        <n-select v-model:value="paperType" :options="types" placeholder="文献类型" clearable style="width: 140px" />
        <n-select v-model:value="verification" :options="verifs" placeholder="核实状态" clearable style="width: 140px" />
        <span style="color: #888">共 {{ total }} 篇</span>
      </n-space>
    </n-card>
    <n-empty v-if="!items.length" description="还没有论文，去「导入中心」导入聊天记录吧" />
    <n-card v-for="p in items" :key="p.id" hoverable size="small" style="cursor: pointer" class="paper-row" @click="router.push(`/paper/${p.id}`)">
      <div style="font-weight: 600">{{ p.title }}</div>
      <div v-if="p.one_liner" style="color: #555; margin: 4px 0">{{ p.one_liner }}</div>
      <n-space size="small" align="center">
        <n-tag size="small" type="info">{{ p.paper_type }}</n-tag>
        <VerifyBadge :value="p.verification" :correction="p.has_correction" />
        <n-tag v-for="c in p.categories" :key="c.id" size="small" type="success">{{ c.name }}</n-tag>
        <span v-if="p.followup_count" style="color: #888">追问 {{ p.followup_count }}</span>
      </n-space>
    </n-card>
    <n-pagination v-if="total > pageSize" v-model:page="page" :page-size="pageSize" :item-count="total" />
  </n-space>
</template>
