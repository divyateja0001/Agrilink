import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

const certificatePath = process.env.AGRILINK_HTTPS_CERT
const certificateKeyPath = process.env.AGRILINK_HTTPS_KEY

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: process.env.AGRILINK_DEV_HOST || '127.0.0.1',
    port: 5173,
    strictPort: true,
    https: certificatePath && certificateKeyPath ? {
      cert: fs.readFileSync(certificatePath),
      key: fs.readFileSync(certificateKeyPath),
    } : undefined,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/uploads': 'http://127.0.0.1:5000',
    },
  },
})
