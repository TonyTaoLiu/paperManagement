<script setup lang="ts">
import { NAlert, NButton, NCard, NEmpty, NInput, NModal, NPopconfirm, NSelect, NSpace, NTag, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const message = useMessage()
const tree = ref<any[]>([])
const editing = ref<any>(null)
const form = ref({ name: '', description: '', parent_id: null as number | null })
const proposal = ref<any>(null)
const busy = ref(false)

const flat = computed(() => {
  const out: any[] = []
  const walk = (ns: any[], depth: number) => ns.forEach((n) => (out.push({ ...n, depth }), walk(n.children, depth + 1)))
  walk(tree.value, 0)
  return out
})
const parentOptions = computed(() => [{ label: '（顶层）', value: null as any }, ...flat.value.filter((n) => n.id !== editing.value?.id).map((n) => ({ label: '　'.repeat(n.depth) + n.name, value: n.id }))])

async function load() {
  tree.value = await api('/categories')
}
function openNew(parent: number | null = null) {
  editing.value = { id: null }
  form.value = { name: '', description: '', parent_id: parent }
}
function openEdit(n: any) {
  editing.value = n
  form.value = { name: n.name, description: n.description, parent_id: n.parent_id }
}
async function save() {
  if (!form.value.name.trim()) return
  if (editing.value.id) await api(`/categories/${editing.value.id}`, { method: 'PATCH', body: JSON.stringify({ ...form.value, move: true }) })
  else await api('/categories', { method: 'POST', body: JSON.stringify(form.value) })
  editing.value = null
  await load()
}
async function remove(n: any) {
  await api(`/categories/${n.id}`, { method: 'DELETE' })
  await load()
}
async function usePreset() {
  try {
    await api('/categories/preset', { method: 'POST' })
    await load()
  } catch (e: any) {
    message.error(String(e))
  }
}
async function propose() {
  busy.value = true
  let t = await api('/categories/propose', { method: 'POST' })
  while (t.status === 'running') {
    await new Promise((r) => setTimeout(r, 1000))
    t = await api(`/tasks/${t.id}`)
  }
  busy.value = false
  if (t.status === 'error') message.error(t.error)
  else proposal.value = t.result
}
async function applyProposal() {
  await api('/categories/apply-proposal', { method: 'POST', body: JSON.stringify(proposal.value) })
  proposal.value = null
  await load()
}
onMounted(load)
</script>

<template>
  <n-space vertical>
    <n-card title="分类体系（研究主题）">
      <n-space>
        <n-button type="primary" @click="openNew(null)" id="add-cat">新建顶层类别</n-button>
        <n-button @click="usePreset" v-if="!tree.length" id="preset-btn">使用神经调控默认体系</n-button>
        <n-button @click="propose" :loading="busy">让 LLM 根据已导入论文建议体系</n-button>
      </n-space>
      <n-alert v-if="proposal" type="info" style="margin-top: 12px" title="LLM 建议的分类体系">
        <div v-for="c in proposal.categories" :key="c.name">
          <b>{{ c.name }}</b> — {{ c.description }}
          <div v-for="s in c.children" :key="s.name" style="margin-left: 16px">· {{ s.name }}：{{ s.description }}</div>
        </div>
        <n-space style="margin-top: 8px"><n-button size="small" type="primary" @click="applyProposal">采用</n-button><n-button size="small" @click="proposal = null">放弃</n-button></n-space>
      </n-alert>
    </n-card>
    <n-empty v-if="!tree.length" description="还没有分类体系：可先用默认体系，或让 LLM 建议" />
    <n-card v-for="n in flat" :key="n.id" size="small" :style="{ marginLeft: n.depth * 28 + 'px' }" class="cat-row">
      <n-space justify="space-between" align="center">
        <div>
          <b>{{ n.name }}</b> <n-tag size="small">{{ n.n_papers }} 篇</n-tag>
          <div style="color: #777">{{ n.description }}</div>
        </div>
        <n-space size="small">
          <n-button size="tiny" @click="openNew(n.id)">加子类</n-button>
          <n-button size="tiny" @click="openEdit(n)">编辑</n-button>
          <n-popconfirm @positive-click="remove(n)"><template #trigger><n-button size="tiny" type="error" quaternary>删除</n-button></template>删除后子类会上移一级，论文不会被删除。</n-popconfirm>
        </n-space>
      </n-space>
    </n-card>
    <n-modal :show="!!editing" preset="card" :title="editing?.id ? '编辑类别' : '新建类别'" style="width: 480px" @close="editing = null" @mask-click="editing = null">
      <n-space vertical>
        <n-input v-model:value="form.name" placeholder="类别名" />
        <n-input v-model:value="form.description" type="textarea" placeholder="一句话描述（用于自动归类，越具体越准）" :rows="3" />
        <n-select v-model:value="form.parent_id" :options="parentOptions" />
        <n-button type="primary" @click="save">保存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>
