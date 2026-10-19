import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import { routes } from './routes'

createApp(App).use(createRouter({ history: createWebHashHistory(), routes })).mount('#app')
