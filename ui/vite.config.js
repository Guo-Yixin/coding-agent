import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.VITE_DASHBOARD_API_BASE_URL || 'http://127.0.0.1:2024'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 3000,
    proxy: {
      '/dashboard/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
