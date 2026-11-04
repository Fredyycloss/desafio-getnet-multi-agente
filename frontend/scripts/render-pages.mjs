// Renders JavaScript-dependent official pages for the knowledge refresh.
// Usage: node scripts/render-pages.mjs <input.json: [url,...]> <output.json>
// Uses the Chromium installed for the Playwright tests; one page at a time, ~1 s apart.
import { readFileSync, writeFileSync } from 'node:fs'
import { chromium } from '@playwright/test'

const [input, output] = process.argv.slice(2)
const urls = JSON.parse(readFileSync(input, 'utf8'))
const browser = await chromium.launch()
const context = await browser.newContext({ userAgent: 'Mozilla/5.0 (compatible; KnowledgeIndexer/3.0; +https://www.getnet.net/)', locale: 'pt-BR' })
const results = {}
for (const url of urls) {
  const page = await context.newPage()
  try {
    const host = new URL(url).hostname
    if (!['site.getnet.com.br', 'www.getnet.net'].includes(host)) throw new Error('outside allowlist')
    // Tracker-heavy pages never reach network idle: wait for the DOM plus a short settle time.
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.waitForTimeout(2500)
    results[url] = { ok: true, html: await page.content() }
  } catch (error) {
    results[url] = { ok: false, error: String(error).slice(0, 200) }
  } finally {
    await page.close()
  }
  process.stdout.write('.')
  await new Promise(resolve => setTimeout(resolve, 800 + Math.random() * 600))
}
await browser.close()
writeFileSync(output, JSON.stringify(results))
console.log(`rendered ${Object.values(results).filter(r => r.ok).length}/${urls.length}`)
