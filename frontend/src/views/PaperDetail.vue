<script setup lang="ts">
import { NAlert, NButton, NCard, NCollapse, NCollapseItem, NDescriptions, NDescriptionsItem, NInput, NSelect, NSpace, NTag, useMessage } from 'naive-ui'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import VerifyBadge from '../components/VerifyBadge.vue'

const props = defineProps<{ id: string }>()
const router = useRouter()
const message = useMessage()
const p = ref<any>(null)
const related = ref<any[]>([])
const editing = ref(false)
const draft = ref<any>({ fields: {}, sections: {} })

const sectionNames: Record<string, string> = {
  background: '1. 研究背景与问题',
  methods: '2. 研究方法与数据',
  results: '3. 重要结果与结论',
  team: '4. 团队与前后文献',
  critique: '5. 批判性思考',
  key_numbers: '关键数字',
}
const entityNames: Record<string, string> = { modality: '数据模态', method: '方法', dataset: '数据集', device: '设备', disease: '疾病', species: '物种', insight: '洞见/原则' }
const originLabel: Record<string, string> = { ai: 'AI 抽取', user: '用户确认', metadata: '元数据库' }
const verifs = ['全文已读', '部分章节', '仅摘要', '无法访问', '未核实'].map((v) => ({ label: v, value: v }))

async function load() {
  p.value = await api(`/papers/${props.id}`)
  related.value = await api(`/papers/${props.id}/related`)
  editing.value = false
}
function startEdit() {
  draft.value = {
    fields: { one_liner: p.value.one_liner, verification: p.value.verification, url: p.value.url, year: p.value.year, venue: p.value.venue },
    sections: Object.fromEntries(Object.entries(p.value.sections).map(([k, v]: any) => [k, v.content_md])),
  }
  editing.value = true
}
async function save() {
  p.value = await api(`/papers/${props.id}`, { method: 'PATCH', body: JSON.stringify(draft.value) })
  editing.value = false
  message.success('已保存（标记为用户确认）')
}
onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <n-space vertical v-if="p">
    <n-button text @click="router.push('/library')">← 返回论文库</n-button>
    <n-card>
      <h2 style="margin: 0 0 8px">{{ p.title }}</h2>
      <n-space align="center" size="small">
        <n-tag type="info" size="small">{{ p.paper_type }}</n-tag>
        <VerifyBadge :value="p.verification" :correction="p.has_correction" />
        <n-tag v-for="c in p.categories" :key="c.id" type="success" size="small">{{ c.name }}</n-tag>
        <a v-if="p.url" :href="p.url" target="_blank" rel="noopener">原文链接</a>
        <a v-if="p.code_url" :href="p.code_url" target="_blank" rel="noopener">代码</a>
        <n-button size="small" @click="router.push({ path: '/graph', query: { view: 'paper', focus: p.id } })">在图谱中查看</n-button>
        <n-button size="small" @click="editing ? (editing = false) : startEdit()">{{ editing ? '取消编辑' : '编辑' }}</n-button>
      </n-space>
      <n-descriptions :column="3" size="small" style="margin-top: 12px">
        <n-descriptions-item label="年份">{{ p.year ?? '—' }}</n-descriptions-item>
        <n-descriptions-item label="期刊/来源">{{ p.venue ?? '—' }}</n-descriptions-item>
        <n-descriptions-item label="DOI">{{ p.doi ?? '—' }}</n-descriptions-item>
        <n-descriptions-item v-if="p.authors.length" label="作者" :span="3">{{ p.authors.join(', ') }}</n-descriptions-item>
      </n-descriptions>
    </n-card>

    <n-card title="一句话核心结论">
      <n-input v-if="editing" v-model:value="draft.fields.one_liner" />
      <template v-else>
        {{ p.one_liner || '（暂无）' }}
        <n-tag v-if="p.user_edited.includes('one_liner')" size="tiny" type="success" style="margin-left: 8px">用户确认</n-tag>
      </template>
    </n-card>
    <n-card v-if="editing" title="核实状态"><n-select v-model:value="draft.fields.verification" :options="verifs" style="width: 200px" /></n-card>

    <n-card v-for="(label, kind) in sectionNames" :key="kind" :title="label" size="small" v-show="p.sections[kind] || editing">
      <template #header-extra>
        <n-tag v-if="p.sections[kind]" size="tiny" :type="p.sections[kind].origin === 'user' ? 'success' : 'default'">{{ originLabel[p.sections[kind].origin] }}</n-tag>
      </template>
      <n-input v-if="editing" v-model:value="draft.sections[kind]" type="textarea" :autosize="{ minRows: 3 }" />
      <pre v-else style="white-space: pre-wrap; font-family: inherit; margin: 0">{{ p.sections[kind]?.content_md }}</pre>
    </n-card>
    <n-button v-if="editing" type="primary" @click="save">保存修改</n-button>

    <n-card v-if="Object.keys(p.entities).length" title="实体标签" size="small">
      <div v-for="(names, type) in p.entities" :key="type" style="margin-bottom: 6px">
        <span style="color: #888; margin-right: 8px">{{ entityNames[type] ?? type }}</span>
        <n-tag v-for="n in names" :key="n" size="small" style="margin-right: 4px">{{ n }}</n-tag>
      </div>
    </n-card>

    <n-card v-if="p.followups.length" :title="`追问线程（${p.followups.length}）`" size="small" id="followups">
      <n-collapse>
        <n-collapse-item v-for="f in p.followups" :key="f.id" :name="f.id">
          <template #header>
            <n-tag v-if="f.is_correction" type="warning" size="small" style="margin-right: 6px">纠错</n-tag>
            第 {{ f.turn_index }} 轮：{{ f.question.slice(0, 60) }}
          </template>
          <p style="color: #555"><b>问：</b>{{ f.question }}</p>
          <pre style="white-space: pre-wrap; font-family: inherit">{{ f.answer_md }}</pre>
        </n-collapse-item>
      </n-collapse>
    </n-card>

    <n-card title="相关论文" size="small">
      <n-alert v-if="!related.length" type="info" :show-icon="false">暂无相关论文（语义向量尚未生成，请先在设置页下载嵌入模型）。</n-alert>
      <div v-for="r in related" :key="r.id" style="margin-bottom: 6px; cursor: pointer" @click="router.push(`/paper/${r.id}`)">
        <n-tag size="small" :type="r.relation === 'similar' ? 'default' : 'warning'">{{ r.relation }}</n-tag>
        {{ r.title }}
        <span style="color: #888"> · {{ r.evidence }}</span>
      </div>
    </n-card>
  </n-space>
</template>
