// Screenshots for docs/evidence/observability/: the Jaeger trace of a real request (by its API
// trace_id), the Grafana dashboard and the Prometheus alert rules.
//   node scripts/observability-shots.mjs <trace_id> <out_dir>
import { chromium } from '@playwright/test'

const [traceId, out] = process.argv.slice(2)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
async function shot(url, name, wait = 4000, selector = null) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  if (selector) await page.waitForSelector(selector, { timeout: 30000 }).catch(() => {})
  await page.waitForTimeout(wait)
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: false })
  console.log('saved', name)
}
await shot(`http://localhost:16686/trace/${traceId}`, '01-jaeger-trace-of-one-chat-turn', 5000, 'text=getnet-assist-api')
await shot('http://localhost:3000/d/getnet-assist/getnet-assist?orgId=1&from=now-30m&to=now&refresh=off', '02-grafana-dashboard', 8000)
await shot('http://localhost:9090/alerts', '03-prometheus-alert-rules', 3000)
await browser.close()
