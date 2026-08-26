import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/analyze': {
        target: 'http://aiplag-production.up.railway.app',
        changeOrigin: true,
      },
      '/subscribe': {
        target: 'http://aiplag-production.up.railway.app',
        changeOrigin: true,
      },
    },
  },
})
