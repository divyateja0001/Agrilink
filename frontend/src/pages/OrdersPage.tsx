import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarDays, CheckCircle2, FileDown, HandCoins, MapPin, MessageSquare, Navigation, PackageCheck, Star, Truck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { dateTime, EmptyState, ErrorState, Field, LoadingPage, PageTitle, StatusBadge, inr, shortDate } from '@/components/common'
import { api, makeIdempotencyKey } from '@/lib/api'
import type { Order, Session } from '@/lib/types'

const renderNow = Date.now()
type Action = 'dispatch' | 'receipt' | 'tracking' | 'comment' | 'complaint'
type RazorpayCheckout = { open: () => void; on: (event: string, callback: (response: { error?: { description?: string } }) => void) => void }
type RazorpayWindow = Window & { Razorpay?: new (options: Record<string, unknown>) => RazorpayCheckout }

export function OrdersPage({ session }: { session: Session }) {
  const queryClient = useQueryClient()
  const orders = useQuery({ queryKey: ['orders'], queryFn: () => api<{ items: Order[] }>('/api/orders') })
  const paymentConfig = useQuery({ queryKey: ['payment-config'], queryFn: () => api<{ enabled: boolean; key_id?: string; message?: string }>('/api/payments/config'), enabled: session.roles.includes('buyer') })
  const [active, setActive] = useState<Order>()
  const [action, setAction] = useState<Action>()
  const [payingOrderId, setPayingOrderId] = useState('')
  const run = useMutation({
    mutationFn: async ({ order, kind, body, evidence = [] }: { order: Order; kind: string; body: unknown; evidence?: File[] }) => {
      const result = await api<{ id?: string }>(`/api/orders/${order.id}/${kind}`, { method: 'POST', body: JSON.stringify(body), idempotencyKey: ['dispatches', 'receipts'].includes(kind) ? makeIdempotencyKey(kind) : undefined })
      if (kind === 'disputes' && result.id) for (const file of evidence.slice(0, 5)) { const form = new FormData(); form.set('photo', file); await api(`/api/disputes/${result.id}/evidence`, { method: 'POST', body: form }) }
      return result
    },
    onSuccess: () => { toast.success('Order updated'); setActive(undefined); setAction(undefined); void queryClient.invalidateQueries({ queryKey: ['orders'] }) },
    onError: (error: Error) => toast.error(error.message),
  })
  const open = (order: Order, nextAction: Action) => { setActive(order); setAction(nextAction) }
  const pay = async (order: Order) => {
    if (payingOrderId) return
    setPayingOrderId(order.id)
    try {
      const config = paymentConfig.data
      if (!config?.enabled) throw new Error(config?.message || 'Razorpay test payment is not configured.')
      await loadRazorpay()
      const paymentOrder = await api<{ razorpay_order_id: string; amount_paise: number; currency: string; key_id: string }>(`/api/orders/${order.id}/razorpay-order`, { method: 'POST', body: JSON.stringify({}) })
      const Razorpay = (window as RazorpayWindow).Razorpay
      if (!Razorpay) throw new Error('Razorpay Checkout could not be loaded.')
      await openRazorpayCheckout(Razorpay, paymentOrder, order, session, async (response) => {
        await api(`/api/orders/${order.id}/razorpay-verify`, { method: 'POST', body: JSON.stringify(response) })
        toast.success('Razorpay test payment verified')
        await queryClient.invalidateQueries({ queryKey: ['orders'] })
      })
    } catch (failure) { toast.error(failure instanceof Error ? failure.message : 'Test payment could not start.') }
    finally { setPayingOrderId('') }
  }

  return <>
    <PageTitle title="Orders and delivery" description="Track delivery and payment independently. Partial dispatches and receipts keep the remaining quantity visible." actions={<>{session.roles.includes('buyer') ? <Button asChild><a href="/tracking"><Navigation />Track vehicles</a></Button> : null}<Button asChild variant="outline"><a href="/api/orders/export.csv"><FileDown />CSV</a></Button></>} />
    {orders.isLoading ? <LoadingPage /> : orders.error ? <ErrorState error={orders.error} retry={() => void orders.refetch()} /> : !orders.data?.items.length ? <EmptyState icon={PackageCheck} title="No orders" body="Confirmed offers create supplier orders and reserve stock." /> : <div className="space-y-5">{orders.data.items.map((order) => <OrderCard key={order.id} order={order} session={session} open={open} pay={() => void pay(order)} paymentEnabled={paymentConfig.data?.enabled ?? false} paymentPending={payingOrderId === order.id} />)}</div>}
    <Dialog open={!!active} onOpenChange={(value) => { if (!value) { setActive(undefined); setAction(undefined) } }}><DialogContent className="max-h-[92vh] overflow-y-auto"><DialogHeader><DialogTitle className="capitalize">{action} · {active?.order_number}</DialogTitle><DialogDescription>Changes are validated against the latest order state on the server.</DialogDescription></DialogHeader>{active && action ? <ActionForm order={active} action={action} session={session} submit={(kind, body, evidence) => run.mutate({ order: active, kind, body, evidence })} /> : null}</DialogContent></Dialog>
  </>
}

function OrderCard({ order, session, open, pay, paymentEnabled, paymentPending }: { order: Order; session: Session; open: (order: Order, action: Action) => void; pay: () => void; paymentEnabled: boolean; paymentPending: boolean }) {
  const ordered = order.lines.reduce((sum, line) => sum + line.agreed_quantity_kg, 0)
  const dispatched = order.lines.reduce((sum, line) => sum + line.dispatched_kg, 0)
  const received = order.lines.reduce((sum, line) => sum + line.received_kg, 0)
  const urgent = (new Date(order.delivery_deadline).getTime() - renderNow) / 86400000 <= 3 && dispatched < ordered
  const supplier = session.roles.some((role) => role === 'farmer' || role === 'fpo_manager')
  const buyer = session.roles.includes('buyer')
  const trackingChoices = nextTrackingChoices(order, session)
  const deliveryMode = order.delivery_mode === 'seller_delivery' ? 'Seller delivery' : 'Buyer pickup'
  const latestDispatch = order.dispatches.at(-1)
  return <Card className="overflow-hidden border-border/80 shadow-sm">
    <CardHeader className="border-b bg-[#fbfcf7] p-4 sm:p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><CardTitle className="text-lg">{order.order_number}</CardTitle><StatusBadge status={order.status} /><StatusBadge status={order.payment_status} /></div>
          <CardDescription className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1"><span>{order.lines.map((line) => line.crop).join(', ')}</span><span aria-hidden="true">·</span><span>{buyer ? order.supplier?.name : order.coordinating_fpo?.name || 'Direct buyer order'}</span></CardDescription>
        </div>
        <div className="rounded-xl border bg-white px-4 py-2.5 sm:text-right"><p className="text-xs text-muted-foreground">Order value</p><p className="text-lg font-semibold text-primary">{inr(order.total_paise)}</p></div>
      </div>
    </CardHeader>
    <CardContent className="p-4 sm:p-5">
      {urgent ? <Alert className="mb-5 border-[#e4c275] bg-[#fff8e8]"><AlertTriangle /><AlertTitle>Deadline approaching</AlertTitle><AlertDescription>{ordered - dispatched} kg still needs dispatch.</AlertDescription></Alert> : null}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <section className="grid gap-4 rounded-2xl border bg-secondary/35 p-4 sm:grid-cols-2" aria-label="Fulfillment progress"><Meter label="Dispatched" value={dispatched} total={ordered} /><Meter label="Received" value={received} total={ordered} /></section>
          <section className="overflow-hidden rounded-2xl border" aria-label="Order quantities">
            {order.lines.map((line) => <div key={line.id} className="grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-5"><div className="col-span-2 sm:col-span-1"><p className="font-semibold">{line.crop}</p><p className="text-xs text-muted-foreground">{line.variety} · Grade {line.quality_grade}</p></div><Quantity label="Agreed" value={line.agreed_quantity_kg} /><Quantity label="Reserved" value={line.reserved_remaining_kg} /><Quantity label="Sent" value={line.dispatched_kg} /><Quantity label="Received" value={line.received_kg} /></div>)}
          </section>
          {order.tracking_events.length ? <section className="rounded-2xl border p-4" aria-label="Shipment journey"><div className="mb-4 flex items-center justify-between gap-3"><div><p className="font-semibold">Shipment journey</p>{latestDispatch ? <p className="text-xs text-muted-foreground">Dispatch {latestDispatch.reference}</p> : null}</div><MapPin className="size-5 text-primary" /></div><ol className="space-y-4 border-l-2 border-primary/20 pl-5">{order.tracking_events.map((event) => <li key={event.id} className="relative"><CheckCircle2 className="absolute -left-[31px] top-0 size-5 rounded-full bg-background text-primary" /><b className="text-sm capitalize">{event.status.replaceAll('_', ' ')}</b><p className="text-xs text-muted-foreground">{dateTime(event.created_at)}{event.note ? ` · ${event.note}` : ''}</p></li>)}</ol></section> : null}
        </div>
        <aside className="space-y-4">
          <section className="rounded-2xl border p-4"><p className="mb-3 font-semibold">Delivery details</p><dl className="space-y-3 text-sm"><Detail icon={Truck} label="Mode" value={deliveryMode} /><Detail icon={CalendarDays} label="Due date" value={shortDate(order.delivery_deadline)} /><Detail icon={HandCoins} label="Payment" value={buyer ? `${inr(order.payable_paise)} payable` : order.payment_status.replaceAll('_', ' ')} /></dl></section>
          <section className="rounded-2xl border p-3"><p className="px-1 pb-2 text-sm font-semibold">Order actions</p><div className="grid grid-cols-2 gap-2">
            {supplier && order.lines.some((line) => line.reserved_remaining_kg > 0) ? <Button size="sm" onClick={() => open(order, 'dispatch')}><Truck />Dispatch</Button> : null}
            {buyer && dispatched > received ? <Button size="sm" onClick={() => open(order, 'receipt')}><PackageCheck />Receive</Button> : null}
            {trackingChoices.length ? <Button size="sm" variant="outline" onClick={() => open(order, 'tracking')}><MapPin />Update tracking</Button> : null}
            {buyer && order.payable_paise > 0 ? <Button size="sm" variant="outline" disabled={!paymentEnabled || paymentPending} title={!paymentEnabled ? 'Configure Razorpay test credentials in backend/.env' : undefined} onClick={pay}><HandCoins />{paymentPending ? 'Opening…' : 'Pay test'}</Button> : null}
            {buyer && order.dispatches.some((dispatch) => dispatch.tracking_assigned) ? <Button size="sm" variant="outline" asChild><a href="/tracking"><Navigation />Track vehicle</a></Button> : null}
            <Button size="sm" variant="outline" onClick={() => open(order, 'comment')}><MessageSquare />Comment</Button>
            <Button size="sm" variant="outline" onClick={() => open(order, 'complaint')}><AlertTriangle />Report issue</Button>
            {buyer && order.review_eligible ? <Button className="col-span-2" size="sm" variant="outline" asChild><a href={`/reviews?order=${order.id}`}><Star />{order.reviews.length ? 'Edit feedback' : 'Rate supplier'}</a></Button> : null}
          </div></section>
        </aside>
      </div>
    </CardContent>
  </Card>
}

function Meter({ label, value, total }: { label: string; value: number; total: number }) { const percentage = total ? Math.round(value / total * 100) : 0; return <div><div className="mb-2 flex items-end justify-between gap-3"><span className="text-sm font-medium">{label}</span><span className="text-right"><b>{value}/{total} kg</b><small className="ml-2 text-muted-foreground">{percentage}%</small></span></div><Progress value={percentage} /></div> }

function Quantity({ label, value }: { label: string; value: number }) { return <div><p className="text-xs text-muted-foreground">{label}</p><p className="font-medium">{value} kg</p></div> }

function Detail({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) { return <div className="flex items-start gap-3"><span className="rounded-lg bg-secondary p-2 text-primary"><Icon className="size-4" /></span><div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium capitalize">{value}</dd></div></div> }

function nextTrackingChoices(order: Order, session: Session) {
  const current = order.tracking_events.at(-1)?.status || 'confirmed'
  const transitions: Record<string, string[]> = { confirmed: ['preparing'], preparing: ['ready_for_pickup', 'in_transit'], ready_for_pickup: ['picked_up'], picked_up: ['arrived'], in_transit: ['arrived'], partially_received: ['arrived', 'delivered'] }
  const supplier = session.roles.some((role) => role === 'farmer' || role === 'fpo_manager')
  const buyer = session.roles.includes('buyer')
  return (transitions[current] || []).filter((status) => (supplier && ['preparing', 'ready_for_pickup', 'in_transit'].includes(status)) || (buyer && ['picked_up', 'arrived'].includes(status)))
}

function ActionForm({ order, action, session, submit }: { order: Order; action: Action; session: Session; submit: (kind: string, body: unknown, evidence?: File[]) => void }) {
  const line = order.lines[0]
  const trackingChoices = nextTrackingChoices(order, session)
  const drivers = useQuery({ queryKey: ['tracking-drivers'], queryFn: () => api<{items:{id:string;name:string;email:string;phone?:string}[]}>('/api/tracking/drivers'), enabled: action === 'dispatch' })
  const handler = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = new FormData(event.currentTarget)
    if (action === 'dispatch') submit('dispatches', { reference: form.get('reference'), carrier_name: form.get('carrier_name'), carrier_phone: form.get('carrier_phone'), driver_email: form.get('driver_email'), vehicle_registration: form.get('vehicle_registration'), note: form.get('note'), lines: [{ order_line_id: line.id, quantity_kg: form.get('quantity') }] })
    else if (action === 'receipt') submit('receipts', { note: form.get('note'), lines: [{ order_line_id: line.id, quantity_kg: form.get('quantity'), deduction_paise: Number(form.get('deduction') || 0) * 100, deduction_reason: form.get('reason') }] })
    else if (action === 'tracking') submit('tracking', { version: order.version, status: form.get('status'), note: form.get('note') })
    else if (action === 'comment') submit('comments', { body: form.get('body') })
    else submit('disputes', { category: form.get('category'), affected_quantity_kg: form.get('affected_quantity'), requested_resolution: form.get('resolution'), reason: form.get('reason') }, form.getAll('evidence').filter((value): value is File => value instanceof File && value.size > 0))
  }
  return <form className="space-y-4" onSubmit={handler}>{action === 'dispatch' ? <><Field label={`Quantity (maximum ${line.reserved_remaining_kg} kg)`}><Input name="quantity" type="number" min=".001" max={line.reserved_remaining_kg} step=".001" required /></Field><Field label="Dispatch reference"><Input name="reference" required /></Field><Field label="Assigned AgriLink driver"><Select name="driver_email" required disabled={drivers.isLoading}><SelectTrigger><SelectValue placeholder={drivers.isLoading ? 'Loading drivers…' : 'Choose a driver'} /></SelectTrigger><SelectContent>{drivers.data?.items.map(driver=><SelectItem key={driver.id} value={driver.email}>{driver.name} · {driver.phone || driver.email}</SelectItem>)}</SelectContent></Select></Field><Field label="Vehicle registration"><Input name="vehicle_registration" placeholder="AP 16 AB 1234" required /></Field><Field label="Carrier name"><Input name="carrier_name" /></Field><Field label="Carrier phone"><Input name="carrier_phone" /></Field><Field label="Dispatch note"><Textarea name="note" /></Field></> : null}{action === 'receipt' ? <><Field label={`Received quantity (maximum ${line.dispatched_kg - line.received_kg} kg)`}><Input name="quantity" type="number" min=".001" max={line.dispatched_kg - line.received_kg} step=".001" required /></Field><Field label="Deduction (₹)"><Input name="deduction" type="number" min="0" defaultValue="0" /></Field><Field label="Deduction reason"><Input name="reason" /></Field><Field label="Receipt note"><Textarea name="note" /></Field></> : null}{action === 'tracking' ? <><Field label="Tracking status"><Select name="status" required><SelectTrigger><SelectValue placeholder="Choose the next status" /></SelectTrigger><SelectContent>{trackingChoices.map((status) => <SelectItem key={status} value={status} className="capitalize">{status.replaceAll('_', ' ')}</SelectItem>)}</SelectContent></Select></Field><Field label="Tracking note"><Textarea name="note" /></Field></> : null}{action === 'comment' ? <Textarea name="body" minLength={1} placeholder="Participant-only comment" required /> : null}{action === 'complaint' ? <><Field label="Issue type"><Select name="category" defaultValue="crop_damage"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="crop_damage">Crop damage</SelectItem><SelectItem value="quality_mismatch">Quality mismatch</SelectItem><SelectItem value="shortage">Quantity shortage</SelectItem><SelectItem value="late_delivery">Late delivery</SelectItem><SelectItem value="payment_issue">Payment issue</SelectItem><SelectItem value="other">Other</SelectItem></SelectContent></Select></Field><Field label="Affected quantity (kg)"><Input name="affected_quantity" type="number" min=".001" step=".001" /></Field><Field label="Describe the issue"><Textarea name="reason" minLength={10} required /></Field><Field label="Requested resolution"><Textarea name="resolution" /></Field><Field label="Evidence photos (up to 5)"><Input name="evidence" type="file" accept="image/jpeg,image/png,image/webp" multiple /></Field></> : null}<Button className="w-full" variant={action === 'complaint' ? 'destructive' : 'default'}>Submit {action}</Button></form>
}

async function loadRazorpay() {
  if ((window as RazorpayWindow).Razorpay) return
  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-agrilink-razorpay]')
    const script = existing || document.createElement('script')
    const timeout = window.setTimeout(() => reject(new Error('Razorpay Checkout timed out. Check your internet connection or browser privacy settings.')), 15_000)
    script.onload = () => { window.clearTimeout(timeout); resolve() }
    script.onerror = () => { window.clearTimeout(timeout); script.remove(); reject(new Error('Razorpay Checkout is unavailable. Check your internet connection or browser privacy settings.')) }
    if (!existing) { script.src = 'https://checkout.razorpay.com/v1/checkout.js'; script.async = true; script.dataset.agrilinkRazorpay = 'true'; document.head.appendChild(script) }
  })
}

async function openRazorpayCheckout(
  Razorpay: NonNullable<RazorpayWindow['Razorpay']>,
  payment: { razorpay_order_id: string; amount_paise: number; currency: string; key_id: string },
  order: Order,
  session: Session,
  verify: (response: Record<string, string>) => Promise<void>,
) {
  await new Promise<void>((resolve, reject) => {
    let settled = false
    const finish = (callback: () => void) => { if (!settled) { settled = true; callback() } }
    const checkout = new Razorpay({
      key: payment.key_id,
      amount: payment.amount_paise,
      currency: payment.currency,
      order_id: payment.razorpay_order_id,
      name: 'AgriLink',
      description: `${order.order_number} · TEST MODE`,
      prefill: { name: session.user.full_name, email: session.user.email },
      retry: { enabled: true },
      modal: { ondismiss: () => finish(resolve) },
      handler: (response: Record<string, string>) => void verify(response).then(() => finish(resolve)).catch((error) => finish(() => reject(error))),
      theme: { color: '#176B43' },
    })
    checkout.on('payment.failed', (response) => finish(() => reject(new Error(response.error?.description || 'Razorpay test payment failed.'))))
    checkout.open()
  })
}
