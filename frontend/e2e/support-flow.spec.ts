import { expect, test } from '@playwright/test'

test('login → product question → ambiguous menu → numeric selection → attendant → protocol status', async ({ page }) => {
  await page.goto('/')

  // Demo login with a listed synthetic user.
  await expect(page.getByRole('heading', { name: 'Entrar na demonstração' })).toBeVisible()
  await page.getByRole('radio', { name: /cliente1988/ }).check()
  await page.getByRole('textbox', { name: 'PIN' }).fill('1988')
  await page.getByRole('button', { name: 'Entrar' }).click()
  const input = page.getByLabel('Sua pergunta')
  await expect(input).toBeVisible()

  // Product question: Knowledge agent answer with sources.
  await input.fill('A Get Lite tem aluguel mensal?')
  await input.press('Enter')
  await expect(page.getByText('a resposta está na fonte citada [1]')).toBeVisible()
  await expect(page.getByText('Fontes consultadas').first()).toBeVisible()

  // Ambiguous message: clarification menu with a human option.
  await input.fill('Minha máquina está estranha.')
  await input.press('Enter')
  const menu = page.getByLabel('Opções para continuar')
  await expect(menu.getByRole('button', { name: /Problemas de conexão/ })).toBeVisible()
  await expect(menu.getByRole('button', { name: /atendimento humano/ })).toBeVisible()

  // Numeric selection resolves the menu into the specialist's intake question.
  await input.fill('1')
  await input.press('Enter')
  await expect(page.getByText(/não encontra a rede/)).toBeVisible()

  // Attendant: a protocol is created, then its status is queried with the bearer token.
  await page.getByRole('button', { name: 'Falar com atendente' }).click()
  await expect(page.getByText(/Protocolo: GET-/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Consultar solicitação de atendimento' }).click()
  await expect(page.getByText(/Status da solicitação GET-.*aguardando atendente/)).toBeVisible()
})
