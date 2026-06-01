import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    open: false,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 上传 PDF 后服务端会做解析/embedding，响应较慢；默认超时过短会导致浏览器侧 Failed to fetch
        timeout: 600_000,
        proxyTimeout: 600_000,
      },
      '/outputs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 600_000,
        proxyTimeout: 600_000,
      },
    },
  },
})
