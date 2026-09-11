self.addEventListener('push', (event) => {
  let data = { title: 'AgriLink update', body: 'Marketplace activity is available.', link: '/notifications' }
  try { data = { ...data, ...event.data.json() } } catch { /* show the safe default */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: '/favicon.svg',
    badge: '/favicon.svg',
    tag: data.notification_id || data.link,
    data: { link: data.link || '/notifications' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.link || '/notifications', self.location.origin).href
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    const existing = windows.find((windowClient) => new URL(windowClient.url).origin === self.location.origin)
    if (existing) { existing.navigate(target); return existing.focus() }
    return clients.openWindow(target)
  }))
})
