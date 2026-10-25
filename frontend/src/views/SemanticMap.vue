<script setup lang="ts">
import { BarChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { NAlert, NCard, NSpace } from 'naive-ui'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

echarts.use([ScatterChart, BarChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])
const router = useRouter()
const el = ref<HTMLElement>()
const empty = ref(false)
let chart: echarts.ECharts | null = null

onMounted(async () => {
  const pts: any[] = await api('/map')
  if (!pts.length) return (empty.value = true)
  await nextTick()
  chart = echarts.init(el.value!)
  const cats = [...new Set(pts.map((p) => p.category))]
  chart.setOption({
    tooltip: { formatter: (p: any) => `${p.data.title}<br/><span style="color:#888">${p.seriesName}</span>` },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 20, right: 20, top: 40, bottom: 20 },
    xAxis: { show: false, scale: true },
    yAxis: { show: false, scale: true },
    series: cats.map((c) => ({
      type: 'scatter',
      name: c,
      symbolSize: 16,
      label: { show: true, position: 'right', formatter: (p: any) => p.data.title.slice(0, 22), fontSize: 10, color: '#555' },
      data: pts.filter((p) => p.category === c).map((p) => ({ value: [p.x, p.y], title: p.title, id: p.id })),
    })),
  })
  chart.on('click', (p: any) => {
    router.push(`/paper/${p.data.id}`)
  })
  window.addEventListener('resize', () => chart?.resize())
})
onBeforeUnmount(() => chart?.dispose())
</script>

<template>
  <n-space vertical>
    <n-card title="语义地图" size="small">每个点是一篇论文，位置由论文向量降维（t-SNE）得到，距离越近主题越相近；颜色表示所属主题。点击打开详情。</n-card>
    <n-alert v-if="empty" type="info">还没有论文向量。请先在设置页下载嵌入模型，并在「导入中心」导入论文。</n-alert>
    <div ref="el" id="map" style="height: 640px; border: 1px solid #e5e5e5; border-radius: 6px; background: #fff" />
  </n-space>
</template>
