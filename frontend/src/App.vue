<script setup lang="ts">
import { NConfigProvider, NLayout, NLayoutHeader, NLayoutContent, NMenu, NMessageProvider, zhCN, dateZhCN } from 'naive-ui'
import { computed, h } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { navItems } from './routes'

const route = useRoute()
const menu = computed(() =>
  navItems.map((i) => ({ key: i.path, label: () => h(RouterLink, { to: i.path }, () => i.label) })),
)
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-layout style="min-height: 100vh">
        <n-layout-header bordered style="padding: 0 24px; display: flex; align-items: center; gap: 24px">
          <strong style="font-size: 18px; white-space: nowrap">PaperMind 论文记忆库</strong>
          <n-menu mode="horizontal" :value="route.path" :options="menu" />
        </n-layout-header>
        <n-layout-content content-style="padding: 24px">
          <router-view />
        </n-layout-content>
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>
