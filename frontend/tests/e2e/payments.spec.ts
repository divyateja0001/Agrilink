import { expect, test } from '@playwright/test'

test('buyer opens Razorpay test checkout and verifies the returned payment', async ({ page }) => {
  const browserErrors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') browserErrors.push(message.text()) })
  page.on('pageerror', (error) => browserErrors.push(error.message))

  await page.route('https://checkout.razorpay.com/v1/checkout.js', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `window.Razorpay = class {
        constructor(options) { this.options = options; }
        on() {}
        open() { setTimeout(() => this.options.handler({ razorpay_order_id: 'order_browser_test', razorpay_payment_id: 'pay_browser_test', razorpay_signature: 'browser_signature' }), 0); }
      };`,
    })
  })
  await page.route('**/api/orders/*/razorpay-order', async (route) => {
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ razorpay_order_id: 'order_browser_test', amount_paise: 5000, currency: 'INR', key_id: 'rzp_test_browser' }) })
  })
  await page.route('**/api/orders/*/razorpay-verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ payment_status: 'paid', test_mode: true }) })
  })

  await page.goto('/login')
  await page.getByLabel('Email').fill('buyer@agrilink.demo')
  await page.getByLabel('Password').fill('AgriLinkDemo!2026')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/orders')
  await page.getByRole('button', { name: 'Pay test' }).first().click()
  await expect(page.getByText('Razorpay test payment verified')).toBeVisible()
  expect(browserErrors).toEqual([])
})
