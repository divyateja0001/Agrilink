import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const password = 'AgriLinkDemo!2026'

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill('buyer@agrilink.demo')
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
}

const languages = [
  {
    code: 'te',
    dashboardWorkflow: 'పూర్తి మార్కెట్‌ప్లేస్ ప్రక్రియ',
    requirements: 'కొనుగోలు అవసరాలు',
    negotiations: 'కొనుగోలుదారు–సరఫరాదారు చర్చలు',
    orders: 'ఆర్డర్లు మరియు డెలివరీ',
    report: 'సమస్యను నివేదించండి',
    produce: 'సరఫరాదారుల అన్వేషణ',
    search: 'పంట, రకం లేదా ప్రాంతాన్ని వెతకండి',
    settings: 'ప్రొఫైల్ మరియు సంస్థ',
  },
  {
    code: 'hi',
    dashboardWorkflow: 'संपूर्ण बाज़ार प्रक्रिया',
    requirements: 'खरीद आवश्यकताएँ',
    negotiations: 'खरीदार–आपूर्तिकर्ता बातचीत',
    orders: 'ऑर्डर और डिलीवरी',
    report: 'समस्या बताएँ',
    produce: 'आपूर्तिकर्ता खोज',
    search: 'फसल, किस्म या स्थान खोजें',
    settings: 'प्रोफ़ाइल और संगठन',
  },
  {
    code: 'ta',
    dashboardWorkflow: 'முழுமையான சந்தை செயல்முறை',
    requirements: 'கொள்முதல் தேவைகள்',
    negotiations: 'வாங்குபவர்–வழங்குநர் பேச்சுவார்த்தைகள்',
    orders: 'ஆர்டர்களும் விநியோகமும்',
    report: 'சிக்கலைப் புகாரளி',
    produce: 'வழங்குநர் தேடல்',
    search: 'பயிர், வகை அல்லது இடத்தைத் தேடுங்கள்',
    settings: 'சுயவிவரமும் நிறுவனமும்',
  },
] as const

test('Telugu, Hindi, and Tamil localize every primary buyer workflow', async ({ page }) => {
  test.setTimeout(60_000)
  await login(page)

  for (const language of languages) {
    await page.evaluate((code) => localStorage.setItem('agrilink-language', code), language.code)
    await page.goto('/')
    await expect(page.locator('html')).toHaveAttribute('lang', language.code)
    await expect(page.getByText(language.dashboardWorkflow)).toBeVisible()

    await page.goto('/requirements')
    await expect(page.getByRole('heading', { name: language.requirements })).toBeVisible()
    await expect(page.getByText('Procurement requirements')).toHaveCount(0)

    await page.goto('/negotiations')
    await expect(page.getByRole('heading', { name: language.negotiations })).toBeVisible()

    await page.goto('/orders')
    await expect(page.getByRole('heading', { name: language.orders })).toBeVisible()
    await expect(page.getByRole('button', { name: language.report }).first()).toBeVisible()
    await expect(page.getByText('Orders and delivery')).toHaveCount(0)

    await page.goto('/produce')
    await expect(page.getByRole('heading', { name: language.produce })).toBeVisible()
    await expect(page.getByPlaceholder(language.search)).toBeVisible()
    await expect(page.getByText('Supplier discovery')).toHaveCount(0)

    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: language.settings })).toBeVisible()
  }
})
