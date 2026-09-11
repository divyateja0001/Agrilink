import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const password = 'AgriLinkDemo!2026'

async function login(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login$/)
}

test('driver simulation is visible to the buyer and can be stopped', async ({ browser }, testInfo) => {
  const driverContext = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const driver = await driverContext.newPage()
  const driverErrors: string[] = []
  driver.on('pageerror', error => driverErrors.push(error.message))
  await login(driver, 'driver@agrilink.demo')
  await expect(driver).toHaveURL(/\/driver$/)
  await expect(driver.getByRole('heading', { name: 'Driver deliveries' })).toBeVisible()
  await driver.getByRole('combobox', { name: 'Assigned dispatch' }).click()
  await driver.getByRole('option', { name: /AP16-DEMO-TRUCK/ }).click()
  await driver.getByRole('button', { name: 'Simulated' }).click()
  await driver.getByRole('button', { name: 'Start Delivery' }).click()
  await expect(driver.getByRole('button', { name: 'Stop Sharing' })).toBeVisible()
  await expect(driver.getByText('For demonstration only. No phone location is read.')).toBeVisible()
  await testInfo.attach('driver-mobile-tracking', { body: await driver.screenshot({ fullPage: true }), contentType: 'image/png' })

  const buyerContext = await browser.newContext({ viewport: { width: 1280, height: 800 } })
  const buyer = await buyerContext.newPage()
  const buyerErrors: string[] = []
  buyer.on('pageerror', error => buyerErrors.push(error.message))
  await login(buyer, 'buyer@agrilink.demo')
  await buyer.goto('/tracking')
  await expect(buyer.getByRole('heading', { name: 'Live delivery tracking' })).toBeVisible()
  await buyer.getByRole('combobox', { name: 'Dispatch' }).click()
  await buyer.getByRole('option', { name: /AP16-DEMO-TRUCK/ }).click()
  await expect(buyer.getByText('Simulated tracking', { exact: true })).toBeVisible()
  await expect(buyer.getByRole('img', { name: /Dispatch map/ })).toBeVisible()
  await expect(buyer.getByText(/Arrival is a driver status only/)).toBeVisible()
  await testInfo.attach('buyer-desktop-tracking', { body: await buyer.screenshot({ fullPage: true }), contentType: 'image/png' })

  await driver.getByRole('button', { name: 'Stop Sharing' }).click()
  await expect(driver.getByText('stopped', { exact: true })).toBeVisible()
  expect(driverErrors).toEqual([])
  expect(buyerErrors).toEqual([])
  await driverContext.close(); await buyerContext.close()
})

test('assistant answers a general judge question even when provider is limited', async ({ page }) => {
  await login(page, 'buyer@agrilink.demo')
  await page.getByRole('button', { name: 'Procurement assistant' }).click()
  await page.getByLabel(/Ask about suppliers/).fill('What is the AgriLink workflow?')
  await page.getByRole('button', { name: 'Ask assistant' }).click()
  await expect(page.getByText(/workflow is: farmer lists produce/i).last()).toBeVisible({ timeout: 25_000 })
})
