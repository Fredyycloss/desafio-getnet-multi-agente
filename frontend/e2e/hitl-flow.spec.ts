import { expect, test, type Page } from '@playwright/test'

// Set E2E_EVIDENCE_DIR to save screenshots of each step (committed under docs/evidence/hitl/).
const evidence = process.env.E2E_EVIDENCE_DIR
async function shot(page: Page, name: string) {
  if (evidence) await page.screenshot({ path: `${evidence}/${name}.png`, fullPage: true })
}

// Customer asks for a human → operator (web console, individual login) claims and replies →
// the reply appears live in the customer chat with the "Atendente" label → operator resolves →
// the customer sees the resolution summary and the status "resolvido".
test('customer ↔ operator console: claim, live reply, resolution back in the chat', async ({ browser }) => {
  test.setTimeout(150_000) // two pages with live polling; slow on a loaded CPU
  const customer = await browser.newPage()
  await customer.goto('/')
  await customer.getByRole('radio', { name: /cliente1988/ }).check()
  await customer.getByRole('textbox', { name: 'PIN' }).fill('1988')
  await customer.getByRole('button', { name: 'Entrar' }).click()
  await customer.getByRole('button', { name: 'Falar com atendente' }).click()
  const protocolText = await customer.getByText(/Protocolo: GET-\d{8}-[0-9A-F]{6}/).first().textContent()
  const protocol = (protocolText || '').match(/GET-\d{8}-[0-9A-F]{6}/)![0]
  await shot(customer, '01-customer-handoff-queued')

  const operator = await browser.newPage()
  await operator.goto('/operador')
  await operator.getByLabel('Usuário').fill('ana.operadora')
  await operator.getByLabel('Senha').fill('demo-ana-2026')
  await operator.getByRole('button', { name: 'Entrar' }).click()
  await operator.getByRole('button', { name: new RegExp(protocol) }).click()
  await operator.getByRole('button', { name: 'Assumir' }).click()
  await expect(operator.getByText('Atendimento assumido.')).toBeVisible()
  await operator.getByLabel('Texto do operador').fill('Olá, sou a Ana. Já estou verificando sua maquininha.')
  await operator.getByRole('button', { name: 'Responder' }).click()
  await expect(operator.getByText('Mensagem enviada ao cliente.')).toBeVisible()
  await shot(operator, '02-operator-console-claimed-and-replied')

  await expect(customer.getByText('Olá, sou a Ana. Já estou verificando sua maquininha.')).toBeVisible({ timeout: 15000 })
  await expect(customer.getByText('Atendente', { exact: true }).first()).toBeVisible()
  await shot(customer, '03-customer-sees-operator-reply-live')

  // While the human handles the case, the customer's message goes to the ticket.
  const input = customer.getByLabel('Sua pergunta')
  await input.fill('É a Get Smart do caixa 2.')
  await input.press('Enter')
  await expect(operator.getByText('É a Get Smart do caixa 2.')).toBeVisible({ timeout: 15000 })

  await operator.getByLabel('Texto do operador').fill('Técnico agendado para amanhã às 9h.')
  await operator.getByRole('button', { name: 'Resolver' }).click()
  await expect(customer.getByText(/Resumo do atendente: Técnico agendado para amanhã às 9h\./)).toBeVisible({ timeout: 15000 })
  await shot(customer, '04-customer-sees-resolution-summary')
})
