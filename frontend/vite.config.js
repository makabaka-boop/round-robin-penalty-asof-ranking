import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.STANDINGS_URL || 'http://localhost:8000' },
      '/health': { target: process.env.STANDINGS_URL || 'http://localhost:8000' }
    }
  },
  preview: {
    port: 8080,
    host: true,
    proxy: {
      '/api': { target: process.env.STANDINGS_URL || 'http://localhost:8000' },
      '/health': { target: process.env.STANDINGS_URL || 'http://localhost:8000' }
    }
  }
})
