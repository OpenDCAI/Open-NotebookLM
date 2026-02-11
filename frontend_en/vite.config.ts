import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',  // 允许外部访问
    port: 26202,      // 使用你的端口范围
    open: false,      // 服务器环境不自动打开浏览器
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:26201',  // 后端端口
        changeOrigin: true,
      },
      '/outputs': {
        target: 'http://localhost:26201',  // 后端端口
        changeOrigin: true,
      },
    },
  },
})
