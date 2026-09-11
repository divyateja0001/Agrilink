export type ApiError = Error & { status?: number; code?: string }

let csrfToken = ''

export function setCsrfToken(token?: string) {
  csrfToken = token ?? ''
}

export async function api<T>(path: string, options: RequestInit & { idempotencyKey?: string } = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (csrfToken && !['GET', 'HEAD'].includes(options.method ?? 'GET')) headers.set('X-CSRF-Token', csrfToken)
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)
  try {
    const response = await fetch(path, { ...options, headers, credentials: 'include' })
    const contentType = response.headers.get('content-type') ?? ''
    const data = contentType.includes('application/json') ? await response.json() : await response.text()
    if (!response.ok) {
      const error = new Error(data?.message ?? `Request failed (${response.status})`) as ApiError
      error.status = response.status
      error.code = data?.error
      if (response.status === 401 && path !== '/api/auth/login' && path !== '/api/auth/session') {
        window.dispatchEvent(new CustomEvent('agrilink:unauthorized'))
      }
      throw error
    }
    return data as T
  } catch (error) {
    if (error instanceof TypeError) {
      const connectionError = new Error('Cannot reach AgriLink. Check that the backend is running.') as ApiError
      connectionError.code = 'connection_lost'
      throw connectionError
    }
    throw error
  }
}

export const makeIdempotencyKey = (operation: string) => `${operation}-${crypto.randomUUID()}`
