import type { RouteRecordRaw } from 'vue-router'
import Home from './views/Home.vue'
import Import from './views/Import.vue'
import Library from './views/Library.vue'
import PaperDetail from './views/PaperDetail.vue'
import Settings from './views/Settings.vue'

export const navItems = [
  { path: '/', label: '首页' },
  { path: '/import', label: '导入中心' },
  { path: '/library', label: '论文库' },
  { path: '/settings', label: '设置' },
]

export const routes: RouteRecordRaw[] = [
  { path: '/', component: Home },
  { path: '/import', component: Import },
  { path: '/library', component: Library },
  { path: '/paper/:id', component: PaperDetail, props: true },
  { path: '/settings', component: Settings },
]
