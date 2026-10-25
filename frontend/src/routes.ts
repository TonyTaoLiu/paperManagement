import type { RouteRecordRaw } from 'vue-router'
import Home from './views/Home.vue'
import Categories from './views/Categories.vue'
import Digests from './views/Digests.vue'
import Graph from './views/Graph.vue'
import Import from './views/Import.vue'
import Inbox from './views/Inbox.vue'
import Library from './views/Library.vue'
import PaperDetail from './views/PaperDetail.vue'
import QA from './views/QA.vue'
import Recommend from './views/Recommend.vue'
import Review from './views/Review.vue'
import SemanticMap from './views/SemanticMap.vue'
import Settings from './views/Settings.vue'
import Timeline from './views/Timeline.vue'

export const navItems = [
  { path: '/', label: '首页' },
  { path: '/import', label: '导入中心' },
  { path: '/inbox', label: '收件箱' },
  { path: '/library', label: '论文库' },
  { path: '/categories', label: '分类体系' },
  { path: '/graph', label: '知识图谱' },
  { path: '/map', label: '语义地图' },
  { path: '/digests', label: '主题综述' },
  { path: '/timeline', label: '时间线' },
  { path: '/qa', label: '问答' },
  { path: '/recommend', label: '推荐' },
  { path: '/review', label: '回忆' },
  { path: '/settings', label: '设置' },
]

export const routes: RouteRecordRaw[] = [
  { path: '/', component: Home },
  { path: '/import', component: Import },
  { path: '/library', component: Library },
  { path: '/inbox', component: Inbox },
  { path: '/categories', component: Categories },
  { path: '/graph', component: Graph },
  { path: '/map', component: SemanticMap },
  { path: '/digests', component: Digests },
  { path: '/timeline', component: Timeline },
  { path: '/paper/:id', component: PaperDetail, props: true },
  { path: '/qa', component: QA },
  { path: '/recommend', component: Recommend },
  { path: '/review', component: Review },
  { path: '/settings', component: Settings },
]
