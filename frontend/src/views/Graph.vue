<script setup lang="ts">
import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { NButton, NCard, NCheckbox, NCheckboxGroup, NRadioButton, NRadioGroup, NSpace, NTag } from 'naive-ui'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

cytoscape.use(fcose)
const route = useRoute()
const router = useRouter()
const el = ref<HTMLElement>()
const view = ref<'global' | 'paper' | 'concept'>((route.query.view as any) || 'global')
const focus = ref<number | null>(route.query.focus ? Number(route.query.focus) : null)
const types = ref(['paper', 'topic', 'method', 'dataset', 'modality', 'device', 'insight', 'author'])
const typeLabels: Record<string, string> = { paper: '论文', topic: '主题', method: '方法', dataset: '数据集', modality: '数据模态', device: '设备', insight: '洞见/原则', author: '作者/团队', disease: '疾病', species: '物种' }
const selected = ref<any>(null)
const stats = ref({ nodes: 0, edges: 0, communities: 0 })
let cy: cytoscape.Core | null = null

const palette = ['#2f9e6b', '#3b82c4', '#e0892f', '#a855a8', '#c4473b', '#6b7a8f', '#b0a020', '#1f8a9e']
const shape: Record<string, string> = { paper: 'ellipse', topic: 'round-rectangle', method: 'diamond', dataset: 'hexagon', modality: 'tag', device: 'pentagon', insight: 'star', author: 'triangle', disease: 'octagon', species: 'octagon' }
const color: Record<string, string> = { topic: '#555', method: '#c98b2a', dataset: '#2a8cc9', modality: '#8c5bc4', device: '#c94f4f', insight: '#d4a017', author: '#6d7a86', disease: '#999', species: '#999' }
const edgeColor: Record<string, string> = { contradicts: '#c4473b', complements: '#2f9e6b', extends: '#3b82c4', alternative: '#e0892f', similar: '#bbb', same_device: '#c94f4f', same_dataset: '#2a8cc9', same_team: '#6d7a86', borrows_method: '#a855a8' }

async function load() {
  const p = new URLSearchParams({ view: view.value, types: types.value.join(',') })
  if (view.value === 'paper' && focus.value) p.set('focus', String(focus.value))
  const g = await api(`/graph?${p}`)
  stats.value = { nodes: g.nodes.length, edges: g.edges.length, communities: g.communities }
  await nextTick()
  cy?.destroy()
  cy = cytoscape({
    container: el.value,
    elements: [
      ...g.nodes.map((n: any) => ({ data: n })),
      ...g.edges.map((e: any) => ({ data: e })),
    ],
    style: [
      { selector: 'node', style: { label: 'data(label)', 'font-size': 10, 'text-wrap': 'ellipsis', 'text-max-width': '110px', 'text-valign': 'bottom', 'text-margin-y': 3, width: 22, height: 22, 'background-color': '#888' } },
      ...Object.keys(shape).map((t) => ({ selector: `node[type="${t}"]`, style: { shape: shape[t] as any, ...(color[t] ? { 'background-color': color[t] } : {}) } })),
      ...palette.map((c, i) => ({ selector: `node[type="paper"][community=${i}]`, style: { 'background-color': c, width: 30, height: 30 } })),
      { selector: 'node[type="paper"]', style: { 'font-size': 11, 'font-weight': 600 } },
      { selector: 'edge', style: { width: 1.2, 'line-color': '#ccc', 'curve-style': 'bezier', opacity: 0.8 } },
      ...Object.entries(edgeColor).map(([t, c]) => ({ selector: `edge[type="${t}"]`, style: { 'line-color': c, width: t === 'similar' ? 1 : 2.5, ...(t === 'contradicts' ? { 'line-style': 'dashed' as const } : {}) } })),
      { selector: 'edge[type="belongs"]', style: { 'line-color': '#ddd', width: 1 } },
      { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#000' } },
    ],
    layout: { name: 'fcose', animate: false, nodeRepulsion: 9000, idealEdgeLength: 90 } as any,
  })
  cy.on('tap', 'node', (ev) => {
    selected.value = ev.target.data()
  })
  cy.on('tap', (ev) => {
    if (ev.target === cy) selected.value = null
  })
  cy.on('dbltap', 'node[type="paper"]', (ev) => router.push(`/paper/${ev.target.data('paper_id')}`))
  ;(window as any).__cy = cy
}
onMounted(load)
watch([view, types, focus], load)
onBeforeUnmount(() => cy?.destroy())
</script>

<template>
  <n-space vertical>
    <n-card size="small">
      <n-space align="center">
        <n-radio-group v-model:value="view" size="small">
          <n-radio-button value="global">全局图谱</n-radio-button>
          <n-radio-button value="concept">概念/原则</n-radio-button>
          <n-radio-button value="paper" :disabled="!focus">论文中心</n-radio-button>
        </n-radio-group>
        <n-checkbox-group v-model:value="types">
          <n-checkbox v-for="(l, t) in typeLabels" :key="t" :value="t" :label="l" />
        </n-checkbox-group>
        <span style="color: #888">{{ stats.nodes }} 个节点 · {{ stats.edges }} 条边 · {{ stats.communities }} 个社区。双击论文打开详情。</span>
      </n-space>
    </n-card>
    <div style="display: flex; gap: 12px">
      <div ref="el" id="cy" style="flex: 1; height: 640px; border: 1px solid #e5e5e5; border-radius: 6px; background: #fff" />
      <n-card v-if="selected" size="small" style="width: 280px" :title="selected.label">
        <n-tag size="small">{{ typeLabels[selected.type] ?? selected.type }}</n-tag>
        <p v-if="selected.one_liner">{{ selected.one_liner }}</p>
        <n-button v-if="selected.paper_id" size="small" type="primary" @click="router.push(`/paper/${selected.paper_id}`)">打开论文</n-button>
        <n-button v-if="selected.paper_id" size="small" style="margin-left: 6px" @click="(focus = selected.paper_id), (view = 'paper')">以它为中心</n-button>
        <p v-if="selected.n_papers" style="color: #888">关联 {{ selected.n_papers }} 篇论文</p>
      </n-card>
    </div>
  </n-space>
</template>
