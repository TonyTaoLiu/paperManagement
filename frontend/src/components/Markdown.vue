<script setup lang="ts">
import { computed } from 'vue'

// Minimal, safe renderer for the subset used by digests: headings, bullets, `code`, [text](#/paper/1) links.
const props = defineProps<{ source: string }>()
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = (s: string) =>
  esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((#\/paper\/\d+)\)/g, '<a href="$2" class="cite">$1</a>')
const html = computed(() => {
  const out: string[] = []
  let inList = false
  for (const line of props.source.split('\n')) {
    if (line.startsWith('- ')) {
      if (!inList) out.push('<ul>'), (inList = true)
      out.push(`<li>${inline(line.slice(2))}</li>`)
      continue
    }
    if (inList) out.push('</ul>'), (inList = false)
    if (line.startsWith('## ')) out.push(`<h3>${inline(line.slice(3))}</h3>`)
    else if (line.startsWith('# ')) out.push(`<h2>${inline(line.slice(2))}</h2>`)
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`)
  }
  if (inList) out.push('</ul>')
  return out.join('')
})
</script>

<template>
  <div class="md" v-html="html" />
</template>

<style scoped>
.md :deep(code) { background: #f3f3f3; padding: 0 4px; border-radius: 3px }
.md :deep(a.cite) { font-size: 12px; margin-right: 2px; text-decoration: none; background: #e8f4ee; padding: 0 4px; border-radius: 3px }
.md :deep(h3) { margin: 16px 0 6px }
</style>
