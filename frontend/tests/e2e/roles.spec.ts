import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page, TestInfo } from '@playwright/test'

const password = 'AgriLinkDemo!2026'
const clientErrors = new WeakMap<Page, string[]>()

function monitorClientErrors(page: Page) {
  const errors: string[] = []
  clientErrors.set(page, errors)
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test.beforeEach(async ({ page }) => {
  monitorClientErrors(page)
})

test.afterEach(async ({ page }) => {
  expect(clientErrors.get(page) ?? [], 'Browser console/page errors').toEqual([])
})

async function login(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function expectOk(response: Awaited<ReturnType<APIRequestContext['post']>>) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

function dateFromNow(days: number) {
  const value = new Date()
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

test('buyer sees procurement workflow without overflow', async ({ page }) => {
  await login(page, 'buyer@agrilink.demo')
  await expect(page.getByText('Complete marketplace workflow')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy()
  await page.getByRole('link', { name: /Requirements/ }).first().click()
  await expect(page.getByText('1,000 kg Tomato')).toBeVisible()
})

test('buyer can open reviews, matched alerts and persistent assistant', async ({ page }, testInfo) => {
  await login(page, 'buyer@agrilink.demo')
  await page.goto('/reviews')
  await expect(page.getByRole('heading', { name: 'Review & Feedback' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Completed orders', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'My Reviews', exact: true })).toBeVisible()
  await testInfo.attach('reviews-page', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })

  await page.goto('/notifications')
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible()
  await expect(page.getByText('Browser alerts', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Procurement assistant' }).click()
  await expect(page.getByRole('heading', { name: 'AI procurement assistant' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Conversation' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Assistant task' })).toBeVisible()
  await testInfo.attach('assistant-panel', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
})

test('farmer can open ratings and role-aware assistant', async ({ page }) => {
  await login(page, 'farmer.a@agrilink.demo')
  await page.goto('/reviews')
  await expect(page.getByRole('heading', { name: 'Ratings & Reviews' })).toBeVisible()
  await expect(page.locator('main').getByRole('heading', { name: 'Lakshmi Farm', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Procurement assistant' }).click()
  await expect(page.getByRole('heading', { name: 'AI procurement assistant' })).toBeVisible()
  await expect(page.getByText('Ask AgriLink', { exact: true })).toBeVisible()
})

test('buyer can open a structured negotiation', async ({ page }) => {
  await login(page, 'buyer@agrilink.demo')
  await page.getByRole('link', { name: 'Negotiations' }).first().click()
  await expect(page.getByRole('heading', { name: /supplier negotiations/ })).toBeVisible()
  await page.getByText('Annapurna Fields').first().click()
  await expect(page.getByRole('tab', { name: 'Offer history' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Private messages' })).toBeVisible()
  await expect(page.getByText(/250 kg at/).first()).toBeVisible()
})

test('sign out clears the authenticated shell and server session', async ({ page }) => {
  await login(page, 'buyer@agrilink.demo')
  const sidebarSignOut = page.getByRole('button', { name: 'Sign out' })
  if (await sidebarSignOut.isVisible()) {
    await sidebarSignOut.click()
  } else {
    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
  }
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await expect(page.getByText('Meera Reddy')).toHaveCount(0)
  const response = await page.request.get('/api/auth/session')
  expect((await response.json()).authenticated).toBeFalsy()
})

test('buyer can open a delivery listing and start a prefilled requirement', async ({ page }) => {
  await login(page, 'buyer@agrilink.demo')
  await page.getByRole('link', { name: 'Produce' }).first().click()
  await page.getByRole('button', { name: 'Open Tomato listing' }).first().click()
  const listingDialog = page.getByRole('dialog')
  await expect(listingDialog).toContainText('Delivery Available')
  await listingDialog.getByRole('button', { name: 'Create requirement from this listing' }).click()
  await expect(page).toHaveURL(/\/requirements$/)
  await expect(page.getByRole('dialog')).toContainText('New procurement requirement')
  await expect(page.getByRole('dialog')).toContainText('Delivery Required')
})

test('buyer sees delivery tracking and the crop-damage report form', async ({ page }, testInfo) => {
  await login(page, 'buyer@agrilink.demo')
  await page.getByRole('link', { name: 'Orders' }).first().click()
  await expect(page.getByText('Seller delivery').first()).toBeVisible()
  await expect(page.getByText('Partially received', { exact: false }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Track vehicles' })).toBeVisible()
  await testInfo.attach('orders-delivery', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
  await page.getByRole('button', { name: 'Report issue' }).first().click()
  await expect(page.getByRole('dialog')).toContainText('Crop damage')
  await expect(page.locator('input[name="evidence"]')).toBeVisible()
})

test('separate farmer FPO and admin sessions', async ({ browser }) => {
  for (const [email, link, title] of [
    ['farmer.a@agrilink.demo', /Produce/, 'My produce'],
    ['fpo@agrilink.demo', /Members/, 'Authorized member supply'],
    ['admin@agrilink.demo', /Administration/, 'Marketplace administration'],
  ] as const) {
    const context = await browser.newContext()
    const page = await context.newPage()
    const errors = monitorClientErrors(page)
    await login(page, email)
    await page.getByRole('link', { name: link }).first().click()
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    expect(errors, `Browser errors for ${email}`).toEqual([])
    await context.close()
  }
})

test('farmer can select an eligible lot and submit an offer', async ({ page, request }, testInfo: TestInfo) => {
  const suffix = `${testInfo.project.name}-${testInfo.workerIndex}-${Date.now()}`.replace(/[^a-z0-9-]/gi, '').toLowerCase()
  const crop = `QA Crop ${suffix}`
  const buyerEmail = `qa-buyer-${suffix}@agrilink.demo`
  const farmerEmail = `qa-farmer-${suffix}@agrilink.demo`

  const buyerRegistration = await expectOk(await request.post('/api/auth/register', {
    data: {
      email: buyerEmail,
      password,
      full_name: 'QA Buyer',
      organization_name: `QA Buyer ${suffix}`,
      location: 'Vijayawada, Andhra Pradesh',
      role: 'buyer',
    },
  }))
  await expectOk(await request.post('/api/requirements', {
    headers: { 'X-CSRF-Token': buyerRegistration.csrf_token },
    data: {
      crop,
      variety: 'QA Variety',
      quantity_kg: '120',
      acceptable_quality: 'B',
      destination: 'Vijayawada, Andhra Pradesh',
      delivery_mode: 'buyer_pickup',
      delivery_deadline: dateFromNow(10),
      budget_price_inr: '30',
      notes: 'Browser QA requirement',
    },
  }))

  const farmerRegistration = await expectOk(await request.post('/api/auth/register', {
    data: {
      email: farmerEmail,
      password,
      full_name: 'QA Farmer',
      organization_name: `QA Farm ${suffix}`,
      location: 'Guntur, Andhra Pradesh',
      role: 'farmer',
    },
  }))
  const createdLot = await expectOk(await request.post('/api/produce', {
    headers: { 'X-CSRF-Token': farmerRegistration.csrf_token },
    data: {
      crop,
      variety: 'QA Variety',
      quantity_kg: '150',
      asking_price_inr: '27.50',
      quality_grade: 'A',
      location: 'Guntur, Andhra Pradesh',
      delivery_mode: 'buyer_pickup',
      harvest_date: dateFromNow(-1),
      available_from: dateFromNow(0),
      available_until: dateFromNow(10),
      description: 'Fresh browser-tested lot',
    },
  }))
  const capture = await expectOk(await request.post(`/api/produce/${createdLot.id}/photo-capture-session`, { headers: { 'X-CSRF-Token': farmerRegistration.csrf_token }, data: {} }))
  await expectOk(await request.post(`/api/produce/${createdLot.id}/photo`, {
    headers: { 'X-CSRF-Token': farmerRegistration.csrf_token },
    multipart: { capture_token: capture.capture_token, latitude: '16.3', longitude: '80.4', accuracy_m: '25', captured_at: new Date().toISOString(), photo: { name: 'camera.jpg', mimeType: 'image/jpeg', buffer: Buffer.from([0xff, 0xd8, 0xff, 0x00]) } },
  }))

  await login(page, farmerEmail)
  await page.getByRole('link', { name: 'Requirements' }).first().click()
  const requirementCard = page.locator('[data-slot="card"]').filter({ hasText: crop })
  await expect(requirementCard).toBeVisible()
  await requirementCard.getByRole('button', { name: 'Send offer' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByLabel('Your produce lot')).toContainText(crop)
  await expect(page.getByLabel('Quantity (kg)')).toHaveValue('120')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy()

  if (['mobile-390', 'desktop-1536'].includes(testInfo.project.name)) {
    await testInfo.attach(`farmer-offer-${testInfo.project.name}`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    })
  }

  await page.getByRole('button', { name: 'Send offer' }).click()
  await expect(page.getByText('Offer sent')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('link', { name: 'Negotiations' }).first().click()
  await expect(page.getByText(crop).first()).toBeVisible()
})
