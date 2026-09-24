import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import router from './router'
import App from './App.vue'
import './style.css'
import { initLocale, getLocale } from './i18n'
import { useContextStore } from './stores/context'
import { useAuthStore } from './stores/auth'
import { initTheme } from './composables/useTheme'

// 初始化国际化
initLocale()
// 初始化主题（深色模式）
initTheme()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Element Plus 全量注册，locale 跟随应用 i18n
app.use(ElementPlus, { locale: getLocale() === 'zh-CN' ? zhCn : en })

// 初始化认证状态
const authStore = useAuthStore(pinia)
if (authStore.token) {
  authStore.fetchUser()
}

// 路由切换时自动同步全局上下文 store（供全局助手浮层 / 内联小窗感知当前页面）
router.afterEach((to) => {
  const ctx = useContextStore(pinia)
  ctx.syncFromRoute(to.path, to.params as Record<string, string>)
})

app.mount('#app')
