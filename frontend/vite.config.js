import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Port 3000 matches the contract's local URL and the backend's default ALLOWED_ORIGINS.
export default defineConfig({
  plugins: [react()],
  server: { port: 3000, strictPort: true, host: true },
  preview: { port: 3000, strictPort: true, host: true },
})
