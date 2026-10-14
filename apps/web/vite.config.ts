import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig(async () => {
  const { default: tailwindcss } = await import('@tailwindcss/vite')

  return {
    plugins: [react(), tailwindcss()],
  }
})
