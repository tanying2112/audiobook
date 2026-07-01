import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './style.css'
import { initLocale } from './i18n'
import { useContextStore } from './stores/context'

// 初始化国际化
initLocale()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// 路由切换时自动同步全局上下文 store（供全局助手浮层 / 内联小窗感知当前页面）
router.afterEach((to) => {
  const ctx = useContextStore(pinia)
  ctx.syncFromRoute(to.path, to.params as Record<string, string>)
})

app.mount('#app')
