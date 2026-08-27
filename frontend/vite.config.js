import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/analyze': {
        target: 'https://aiplag-production.up.railway.app',
        changeOrigin: true,
      },
      '/subscribe': {
        target: 'https://aiplag-production.up.railway.app',
        changeOrigin: true,
      },
    },
  },
})
