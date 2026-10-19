<script setup lang="ts">
import { NCard, NSpace, NTag, NTimeline, NTimelineItem } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const items = ref<any[]>([])
onMounted(async () => (items.value = await api('/timeline')))
</script>

<template>
  <n-space vertical>
    <n-card title="阅读时间线" size="small">按阅读顺序排列（ChatGPT 导出带时间戳；归档 Markdown 无日期时按对话顺序，可在论文详情中补填阅读日期）。</n-card>
    <n-card>
      <n-timeline>
        <n-timeline-item v-for="p in items" :key="p.id" :title="p.title" :time="p.read_at || `第 ${p.order} 篇`" :content="p.one_liner" style="cursor: pointer" @click="router.push(`/paper/${p.id}`)">
          <template #footer><n-tag v-if="p.year" size="small">{{ p.year }}</n-tag></template>
        </n-timeline-item>
      </n-timeline>
    </n-card>
  </n-space>
</template>
