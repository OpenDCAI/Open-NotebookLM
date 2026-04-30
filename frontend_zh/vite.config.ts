import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8213',
        changeOrigin: true,
      },
      '/outputs': {
        target: 'http://localhost:8213',
        changeOrigin: true,
      },
      '/onlyoffice': {
        target: 'http://localhost:8082',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/onlyoffice/, ''),
      },
    },
  },
})
