import type { RouteRecordRaw } from 'vue-router'
import Home from './views/Home.vue'
import Settings from './views/Settings.vue'

export const navItems = [
  { key: 'home', path: '/', label: '首页' },
  { key: 'settings', path: '/settings', label: '设置' },
]

export const routes: RouteRecordRaw[] = [
  { path: '/', component: Home },
  { path: '/settings', component: Settings },
]
