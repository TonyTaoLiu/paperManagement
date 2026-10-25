<script setup lang="ts">
import { NTag } from 'naive-ui'
import { computed } from 'vue'

const props = defineProps<{ value: string; correction?: boolean }>()
const meta: Record<string, { icon: string; type: 'success' | 'info' | 'error' | 'warning' | 'default' }> = {
  全文已读: { icon: '✅', type: 'success' },
  部分章节: { icon: '📖', type: 'info' },
  仅摘要: { icon: '📄', type: 'info' },
  无法访问: { icon: '⛔', type: 'error' },
  未核实: { icon: '❓', type: 'default' },
}
const m = computed(() => meta[props.value] ?? meta['未核实'])
</script>

<template>
  <span>
    <n-tag size="small" :type="m.type">{{ m.icon }} {{ value }}</n-tag>
    <n-tag v-if="correction" size="small" type="warning" style="margin-left: 4px">⚠️ 有纠错</n-tag>
  </span>
</template>
