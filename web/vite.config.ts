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
  build: {
    // 验收标准: 单个 chunk < 500KB
    chunkSizeWarningLimit: 500,
    // Vite 8 底层是 rolldown: 必须用 rolldownOptions.output.codeSplitting。
    // 注意: 若同时存在 rollupOptions.output.manualChunks, manualChunks 会被忽略。
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            // echarts 的底层 2D 画布引擎(~400KB, 不可 tree-shake): 独立一块 <500KB。
            { name: 'zrender', test: /node_modules[\\/]zrender/, priority: 10 },
            // tree-shaken 后的 echarts 业务模块(~160KB): 独立一块 <500KB。
            // 与 zrender 拆开可避免 >500KB, 且只产生 2 个请求(比 maxSize 切 ~10 块更优)。
            { name: 'echarts', test: /node_modules[\\/]echarts/, priority: 10 },
            // chart.js: 仅 MonitoringDashboard 使用, 单独 chunk。
            { name: 'chartjs', test: /node_modules[\\/]chart\.js/, priority: 10 },
            // wavesurfer.js: 音频波形, 单独 chunk。
            { name: 'wavesurfer', test: /node_modules[\\/]wavesurfer\.js/, priority: 10 },
            // 其余第三方依赖兜底进 vendor, 避免撑大入口 chunk。
            { name: 'vendor', test: /node_modules/, priority: 0 },
          ],
        },
      },
    },
  },
})
