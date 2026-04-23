import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  appType: 'spa',
  plugins: [react()],
  server: {
    port: 5175,
    strictPort: true,
    host: true
  }
})
