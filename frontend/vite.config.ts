import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// VITE_API_PROXY lets the browser test point the dev server at its own API instance.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}
export default defineConfig({ plugins: [react()], server: { port: 5173, proxy: { '/api': env.VITE_API_PROXY || 'http://localhost:8000' } } })
