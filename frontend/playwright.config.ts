import { defineConfig, devices } from '@playwright/test'

// Real UI + real API. The API runs with LLM_PROVIDER=fixture (scripted, deterministic),
// so the flow is reproducible in CI without a model or an API key. The screenshot gallery
// (e2e/ui-gallery.spec.ts) uses E2E_LLM_PROVIDER=replay: recorded cloud answers, no key.
const python = process.env.E2E_PYTHON || 'python3'
const db = `/tmp/getnet-e2e-${Date.now()}.sqlite3`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  use: { baseURL: 'http://localhost:5180', trace: 'retain-on-failure', ...devices['Desktop Chrome'] },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port 8100`,
      cwd: '../backend',
      url: 'http://localhost:8100/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
      env: { PYTHONPATH: '.', LLM_PROVIDER: process.env.E2E_LLM_PROVIDER || 'fixture', LLM_REPLAY_DIR: process.env.E2E_REPLAY_DIR || '', DEMO_TODAY: process.env.E2E_DEMO_TODAY || '',
             CONTEXT_MODE: 'llm', CRITIC_CHALLENGE_MODE: 'false', OLLAMA_ENABLED: 'false', KNOWLEDGE_CRAWL_ENABLED: 'false',
             DATABASE_PATH: db, AUTH_SECRET: 'e2e-secret', LOG_LEVEL: 'WARNING' },
    },
    {
      command: 'npx vite --port 5180 --strictPort',
      url: 'http://localhost:5180',
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_PROXY: 'http://localhost:8100' },
    },
  ],
})
