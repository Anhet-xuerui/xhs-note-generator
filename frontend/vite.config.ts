import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 产物由 FastAPI 直接托管（§10：省掉一个容器），所以用相对 base。
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      '/runs': 'http://127.0.0.1:8000',
      '/prompts': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
