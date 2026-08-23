import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        // 后端所有业务路由(projects/books/llm/ws/auto-run/...)均已迁移至 /api 前缀下，
        // 前端统一用 /api/** 约定，不再需要 strip 前缀。
      },
    },
  },
})
