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
        target: 'http://localhost:18213',
        changeOrigin: true,
      },
      '/outputs': {
        target: 'http://localhost:18213',
        changeOrigin: true,
      },
    },
  },
})
