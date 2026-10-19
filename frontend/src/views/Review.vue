<script setup lang="ts">
import { NButton, NCard, NEmpty, NProgress, NSpace } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const queue = ref<any[]>([])
const total = ref(0)
const flipped = ref(false)
const card = computed(() => queue.value[0])

async function load() {
  queue.value = await api('/review/due?limit=30')
  total.value = queue.value.length
  flipped.value = false
}
async function rate(r: number) {
  await api(`/review/${card.value.paper_id}?rating=${r}`, { method: 'POST' })
  queue.value = queue.value.slice(1)
  flipped.value = false
}
onMounted(load)
</script>

<template>
  <n-space vertical style="max-width: 720px">
    <n-card title="回忆模式" size="small">
      闪卡：正面是论文标题，先自己回忆结论和你当时的质疑，再翻面对照。按 FSRS 间隔重复算法安排下次复习。
      <n-progress v-if="total" type="line" :percentage="Math.round(((total - queue.length) / total) * 100)" style="margin-top: 8px" />
    </n-card>
    <n-empty v-if="!card" description="今天没有需要复习的论文 🎉" />
    <n-card v-else class="flashcard" size="large">
      <h3 style="margin-top: 0">{{ card.title }}</h3>
      <n-button v-if="!flipped" type="primary" @click="flipped = true" id="flip-btn">显示答案</n-button>
      <template v-else>
        <p><b>一句话结论：</b>{{ card.one_liner || '（暂无）' }}</p>
        <div v-if="card.critique.length"><b>当时的批判：</b><div v-for="c in card.critique" :key="c" style="color: #555">· {{ c }}</div></div>
        <n-space style="margin-top: 12px">
          <n-button @click="rate(1)">没想起来</n-button>
          <n-button @click="rate(2)">有点吃力</n-button>
          <n-button type="primary" @click="rate(3)">记得</n-button>
          <n-button type="success" @click="rate(4)">很轻松</n-button>
        </n-space>
      </template>
    </n-card>
  </n-space>
</template>
