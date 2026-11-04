import { expect, test, type Page } from '@playwright/test'

// Screenshot gallery for docs/evidence/ui/ with recorded cloud answers (no key):
//   E2E_GALLERY=1 E2E_LLM_PROVIDER=replay E2E_EVIDENCE_DIR=../docs/evidence/ui npx playwright test ui-gallery
// Each question starts a new conversation, as in the recorded benchmark, so the replayed
// model calls match. Skipped in the normal CI run (fixture provider).
test.skip(!process.env.E2E_GALLERY, 'gallery only (E2E_GALLERY=1)')

const dir = process.env.E2E_EVIDENCE_DIR || 'gallery'
const shot = (page: Page, name: string) => page.screenshot({ path: `${dir}/${name}.png`, fullPage: true })

async function ask(page: Page, text: string) {
  await page.getByRole('button', { name: 'Nova conversa' }).first().click()
  const input = page.getByLabel('Sua pergunta')
  await input.fill(text)
  const reply = page.waitForResponse(r => r.url().includes('/api/chat'), { timeout: 90_000 })
  await input.press('Enter')
  await reply
  await page.waitForTimeout(800)
}

test('UI gallery with replayed cloud answers', async ({ page }) => {
  test.setTimeout(180_000)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Entrar na demonstração' })).toBeVisible()
  await shot(page, '01-login')
  await page.getByRole('radio', { name: /cliente1988/ }).check()
  await page.getByRole('textbox', { name: 'PIN' }).fill('1988')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByLabel('Sua pergunta')).toBeVisible()
  await shot(page, '02-home')

  await ask(page, 'A Get Lite tem aluguel mensal?')
  await expect(page.getByText('Fontes consultadas').first()).toBeVisible({ timeout: 60_000 })
  await shot(page, '03-product-answer-with-sources')

  await ask(page, 'Quando cai o dinheiro das vendas de ontem?')
  await shot(page, '04-customer-data-tool-answer')

  await ask(page, 'Minha máquina está estranha e não sei o que está acontecendo.')
  await expect(page.getByLabel('Opções para continuar')).toBeVisible({ timeout: 60_000 })
  await shot(page, '05-ambiguous-clarification-menu')

  await ask(page, 'A bateria da maquininha está estufada.')
  await expect(page.getByText(/Protocolo do incidente: GET-/).first()).toBeVisible({ timeout: 60_000 })
  await shot(page, '06-physical-risk-safety-handoff')

  await ask(page, 'Essa máquina é uma bomba.')
  await shot(page, '07-figurative-language')

  const operator = await page.context().newPage()
  await operator.setViewportSize({ width: 1280, height: 900 })
  await operator.goto('/operador')
  await operator.getByLabel('Usuário').fill('ana.operadora')
  await operator.getByLabel('Senha').fill('demo-ana-2026')
  await operator.getByRole('button', { name: 'Entrar' }).click()
  await expect(operator.getByRole('button', { name: /GET-/ }).first()).toBeVisible({ timeout: 15_000 })
  await operator.getByRole('button', { name: /GET-/ }).first().click()
  await operator.waitForTimeout(1500)
  await operator.screenshot({ path: `${dir}/08-operator-console-queue.png`, fullPage: true })
})
