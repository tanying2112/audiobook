import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './style.css'
import { initLocale } from './i18n'

// 初始化国际化
initLocale()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
