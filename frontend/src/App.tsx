import { lazy, Suspense, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Bell, ClipboardList, HandCoins, Languages, LayoutDashboard, Leaf, Loader2, LogOut,
  PackageCheck, Settings, ShieldCheck, ShoppingBasket, Sparkles, Sprout, Truck, Users,
} from 'lucide-react'
import { toast, Toaster } from 'sonner'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TooltipProvider } from '@/components/ui/tooltip'
import { InterfaceLanguage } from '@/components/InterfaceLanguage'
import { api, setCsrfToken } from '@/lib/api'
import type { Role, Session, SessionResponse } from '@/lib/types'
import { AdminPage, MembersPage, SettingsPage } from '@/pages/SharedPages'
import { NotificationsPage } from '@/pages/NotificationsPage'
import { Dashboard } from '@/pages/Dashboard'
import { OrdersPage } from '@/pages/OrdersPage'
import { ProducePage } from '@/pages/ProducePage'
import { QuotesPage } from '@/pages/QuotesPage'
import { RequirementsPage } from '@/pages/RequirementsPage'
import { ReviewsPage } from '@/pages/ReviewsPage'
import { BuyerTrackingPage, DriverPage } from '@/pages/TrackingPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: true } },
})
const ProcurementAssistant = lazy(() => import('@/components/ProcurementAssistant'))

const navFor = (role: Role, t: (key: string) => string) => {
  const dashboard = { to: '/', label: t('dashboard'), icon: LayoutDashboard }
  if (role === 'farmer') return [dashboard, { to: '/produce', label: t('produce'), icon: Sprout }, { to: '/requirements', label: t('requirements'), icon: ShoppingBasket }, { to: '/negotiations', label: t('negotiations'), icon: HandCoins }, { to: '/orders', label: t('orders'), icon: Truck }]
  if (role === 'buyer') return [dashboard, { to: '/requirements', label: t('requirements'), icon: ClipboardList }, { to: '/negotiations', label: t('negotiations'), icon: HandCoins }, { to: '/orders', label: t('orders'), icon: PackageCheck }, { to: '/produce', label: t('produce'), icon: ShoppingBasket }]
  if (role === 'fpo_manager') return [dashboard, { to: '/members', label: t('members'), icon: Users }, { to: '/requirements', label: t('requirements'), icon: ShoppingBasket }, { to: '/negotiations', label: t('negotiations'), icon: HandCoins }, { to: '/orders', label: t('orders'), icon: Truck }]
  if (role === 'driver') return [{ to: '/driver', label: 'My deliveries', icon: Truck }]
  return [dashboard, { to: '/admin', label: t('admin'), icon: ShieldCheck }, { to: '/orders', label: t('orders'), icon: PackageCheck }, { to: '/settings', label: t('settings'), icon: Settings }]
}

function LanguagePicker() {
  const { t, i18n } = useTranslation()
  const changeLanguage = (language: 'en' | 'te' | 'hi' | 'ta') => {
    void i18n.changeLanguage(language)
    localStorage.setItem('agrilink-language', language)
    document.documentElement.lang = language
  }
  return <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label={t('language')}><Languages /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => changeLanguage('en')}>English</DropdownMenuItem><DropdownMenuItem onClick={() => changeLanguage('te')}>తెలుగు</DropdownMenuItem><DropdownMenuItem onClick={() => changeLanguage('hi')}>हिन्दी</DropdownMenuItem><DropdownMenuItem onClick={() => changeLanguage('ta')}>தமிழ்</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
}

function LoginPage({ done }: { done: (session: Session) => void }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('buyer@agrilink.demo')
  const [password, setPassword] = useState('AgriLinkDemo!2026')
  const [error, setError] = useState('')
  const login = useMutation({
    mutationFn: () => api<Session>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
    onSuccess: (session) => { setCsrfToken(session.csrf_token); done(session) },
    onError: (failure: Error) => setError(failure.message),
  })
  const demos = [
    ['Buyer', 'buyer@agrilink.demo'], ['Farmer A', 'farmer.a@agrilink.demo'],
    ['FPO manager', 'fpo@agrilink.demo'], ['Driver', 'driver@agrilink.demo'], ['Admin', 'admin@agrilink.demo'],
  ]

  return (
    <main className="min-h-screen px-4 py-8 sm:py-16">
      <div className="mx-auto grid max-w-5xl overflow-hidden rounded-3xl border bg-card shadow-xl lg:grid-cols-2">
        <section className="relative hidden min-h-[640px] overflow-hidden bg-sidebar text-white lg:block">
          <img src="/produce/tomatoes.png" alt="Fresh tomatoes ready for business procurement" className="absolute inset-0 h-full w-full object-cover opacity-35" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#0e3424] via-[#123e2b]/80 to-transparent" />
          <div className="relative flex h-full flex-col justify-between p-10">
            <div className="flex items-center gap-3 text-2xl font-semibold"><Leaf />{t('brand')}</div>
            <div>
              <p className="text-sm font-semibold text-[#f2b84b]">B2B AGRICULTURAL MARKETPLACE</p>
              <h1 className="mt-4 text-4xl font-semibold leading-tight">{t('reliableSupply')}</h1>
              <p className="mt-4 text-white/80">{t('loginStory')}</p>
            </div>
          </div>
        </section>
        <section className="p-6 sm:p-10">
          <div className="mb-8 flex items-center justify-between"><div className="flex items-center gap-3 lg:hidden"><span className="rounded-xl bg-primary p-2 text-white"><Leaf /></span><b className="text-2xl">{t('brand')}</b></div><div className="ml-auto"><LanguagePicker /></div></div>
          <h2 className="text-2xl font-semibold">{t('welcome')}</h2>
          <p className="mt-2 text-sm text-muted-foreground">{t('loginHelp')}</p>
          <form className="mt-7 space-y-5" onSubmit={(event: FormEvent) => { event.preventDefault(); setError(''); login.mutate() }}>
            <div className="space-y-2"><Label htmlFor="email">{t('email')}</Label><Input id="email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></div>
            <div className="space-y-2"><Label htmlFor="password">{t('password')}</Label><Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button className="h-11 w-full" disabled={login.isPending}>{login.isPending && <Loader2 className="animate-spin" />}{t('signIn')}</Button>
          </form>
          <div className="my-7 flex items-center gap-3 text-xs uppercase text-muted-foreground"><span className="h-px flex-1 bg-border" />{t('demoAccounts')}<span className="h-px flex-1 bg-border" /></div>
          <div className="grid grid-cols-2 gap-3">{demos.map(([label, value]) => <Button key={value} type="button" variant="outline" className="h-11" onClick={() => setEmail(value)}>{label}</Button>)}</div>
          <p className="mt-6 text-xs text-muted-foreground">{t('sampleData')} · password <code>AgriLinkDemo!2026</code></p>
        </section>
      </div>
    </main>
  )
}

function Shell({ session, signedOut }: { session: Session; signedOut: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const role = session.roles[0]
  const items = navFor(role, t)
  const organization = session.memberships[0]?.organization
  const notices = useQuery({ queryKey: ['notifications'], queryFn: () => api<{ unread: number }>('/api/notifications') })
  const logout = useMutation({
    mutationFn: () => api('/api/auth/logout', { method: 'POST' }),
    onSettled: async (_data, error) => {
      await queryClient.cancelQueries()
      setCsrfToken()
      queryClient.setQueryData<SessionResponse>(['session'], { authenticated: false })
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
      signedOut()
      navigate('/login', { replace: true })
      if (error) toast.error('Signed out locally. The server could not be reached to revoke the session.')
    },
  })
  const signOutButton = (
    <Button variant="ghost" disabled={logout.isPending} className="w-full justify-start text-white/80 hover:bg-sidebar-accent hover:text-white" onClick={() => logout.mutate()}>
      {logout.isPending ? <Loader2 className="animate-spin" /> : <LogOut />}{logout.isPending ? t('signingOut') : t('signOut')}
    </Button>
  )

  return (
    <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
      <aside className="fixed inset-y-0 hidden w-[248px] flex-col bg-sidebar text-sidebar-foreground md:flex">
        <div className="flex h-20 items-center gap-3 border-b border-sidebar-border px-6"><Leaf /><div><b className="text-lg">{t('brand')}</b><small className="block text-white/60">B2B marketplace</small></div></div>
        <nav className="flex-1 space-y-1 p-4">{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium ${isActive ? 'bg-white text-[#123e2b]' : 'text-white/80 hover:bg-sidebar-accent hover:text-white'}`}><Icon className="size-5" />{label}</NavLink>)}</nav>
        <div className="border-t border-sidebar-border p-4"><p className="truncate text-sm font-medium">{session.user.full_name}</p><p className="truncate text-xs text-white/60">{organization?.name}</p><div className="mt-3">{signOutButton}</div></div>
      </aside>
      <div className="min-w-0 md:col-start-2">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b bg-background/95 px-4 backdrop-blur sm:px-6 lg:px-8">
          <div className="flex items-center gap-2 md:hidden"><Leaf className="text-primary" /><b>{t('brand')}</b></div>
          <div className="hidden md:block"><p className="text-xs font-medium uppercase text-muted-foreground">{organization?.name}</p><p className="text-sm capitalize">{role.replace('_', ' ')}</p></div>
          <div className="flex items-center">
            {['buyer', 'farmer', 'fpo_manager'].includes(role) && <Suspense fallback={null}><ProcurementAssistant trigger={<Button variant="ghost" size="icon" aria-label={t('assistant')}><Sparkles /></Button>} /></Suspense>}
            <LanguagePicker />
            <Button variant="ghost" size="icon" onClick={() => navigate('/notifications')} className="relative" aria-label={t('notifications')}><Bell />{!!notices.data?.unread && <span className="absolute right-1 top-1 size-2 rounded-full bg-[#b46300]" />}</Button>
            <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="Account menu"><Avatar className="size-8"><AvatarFallback>{session.user.full_name[0]}</AvatarFallback></Avatar></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuLabel>{session.user.email}</DropdownMenuLabel><DropdownMenuSeparator /><DropdownMenuItem onClick={() => navigate('/settings')}><Settings />{t('settings')}</DropdownMenuItem><DropdownMenuItem disabled={logout.isPending} onClick={() => logout.mutate()}><LogOut />{logout.isPending ? t('signingOut') : t('signOut')}</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
          </div>
        </header>
        <main className="safe-bottom mx-auto max-w-[1500px] p-4 sm:p-6 lg:p-8">
          <Routes>
            <Route path="/" element={role === 'driver' ? <Navigate to="/driver" replace /> : <Dashboard session={session} />} />
            <Route path="/produce" element={<ProducePage session={session} />} />
            <Route path="/requirements" element={<RequirementsPage session={session} />} />
            <Route path="/negotiations/*" element={<QuotesPage session={session} />} />
            <Route path="/quotations" element={<Navigate to="/negotiations" replace />} />
            <Route path="/orders" element={<OrdersPage session={session} />} />
            <Route path="/tracking" element={<BuyerTrackingPage />} />
            <Route path="/driver" element={role === 'driver' ? <DriverPage session={session} /> : <Navigate to="/" replace />} />
            <Route path="/reviews" element={<ReviewsPage session={session} />} />
            <Route path="/members" element={<MembersPage session={session} />} />
            <Route path="/admin" element={<AdminPage session={session} />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/settings" element={<SettingsPage session={session} />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
      <nav className="fixed inset-x-0 bottom-0 z-30 grid border-t bg-card pb-[env(safe-area-inset-bottom)] md:hidden" style={{ gridTemplateColumns: `repeat(${items.length},1fr)` }}>
        {items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 px-1 text-[10px] ${isActive ? 'text-primary' : 'text-muted-foreground'}`}><Icon className="size-5" /><span className="max-w-full truncate">{label}</span></NavLink>)}
      </nav>
    </div>
  )
}

function Root() {
  const queryClient = useQueryClient()
  const session = useQuery<SessionResponse>({ queryKey: ['session'], queryFn: () => api<SessionResponse>('/api/auth/session'), retry: false })

  useEffect(() => {
    const handleUnauthorized = () => {
      setCsrfToken()
      queryClient.setQueryData<SessionResponse>(['session'], { authenticated: false })
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
    }
    window.addEventListener('agrilink:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('agrilink:unauthorized', handleUnauthorized)
  }, [queryClient])

  useEffect(() => {
    if (session.data?.authenticated) setCsrfToken(session.data.csrf_token)
  }, [session.data])

  if (session.isLoading) return <div className="flex min-h-screen items-center justify-center"><Loader2 className="animate-spin" aria-label="Loading AgriLink" /></div>
  return (
    <Routes>
      <Route path="/login" element={session.data?.authenticated ? <Navigate to="/" replace /> : <LoginPage done={(value) => queryClient.setQueryData(['session'], value)} />} />
      <Route path="/*" element={session.data?.authenticated ? <Shell session={session.data} signedOut={() => queryClient.setQueryData(['session'], { authenticated: false })} /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}

export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter><TooltipProvider><InterfaceLanguage /><Root /><Toaster richColors position="top-right" /></TooltipProvider></BrowserRouter></QueryClientProvider>
}
