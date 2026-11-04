import { expect, test } from '@playwright/test'

// V6 block 2: each home-screen suggestion is answered (sources or account data), never a clarification menu.
const suggestions = [
  { text: 'Qual a diferença entre a Get Clássica e a Get Smart?' },
  { text: 'Quando recebo o dinheiro das minhas vendas?' },
  { text: 'Minha maquininha não conecta à internet. O que faço?' },
  { text: 'Posso vender pelo WhatsApp usando link de pagamento?' },
]

for (const s of suggestions) {
  test(`suggestion answered without a menu: ${s.text}`, async ({ page }) => {
    await page.goto('/')
    await page.getByRole('radio', { name: /cliente1988/ }).check()
    await page.getByRole('textbox', { name: 'PIN' }).fill('1988')
    await page.getByRole('button', { name: 'Entrar' }).click()
    const reply = page.waitForResponse(r => r.url().includes('/api/chat'))
    await page.getByRole('button', { name: new RegExp(s.text.slice(0, 20)) }).click()
    const body = await (await reply).json()
    expect(body.clarification_options ?? []).toHaveLength(0)
    expect(body.orchestration_mode).not.toBe('context_policy_clarification')
    const grounded = (body.sources?.length ?? 0) > 0 || JSON.stringify(body.specialist_observations ?? []).includes('"ok": true')
      || JSON.stringify(body.specialist_observations ?? []).includes('"ok":true')
    expect(grounded).toBe(true)
    await expect(page.getByLabel('Opções para continuar')).toHaveCount(0)
  })
}
