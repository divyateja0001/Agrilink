import { lazy, Suspense, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Bot, Check, HandCoins, Loader2, MessageSquare, PackageCheck, Send, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { dateTime, EmptyState, ErrorState, Field, inr, LoadingPage, PageTitle, shortDate, StatusBadge } from '@/components/common'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, makeIdempotencyKey } from '@/lib/api'
import type { NegotiationDetail, Quote, Session } from '@/lib/types'

type CounterValues = {
  quantity_kg: number
  price_inr_per_kg: number
  quality_grade: string
  delivery_date: string
  delivery_terms: string
  note: string
}
type CounterDraft = Partial<CounterValues> & { notes?: string }
const ProcurementAssistant = lazy(() => import('@/components/ProcurementAssistant'))

function statusText(status: string, t: (key: string) => string) {
  if (status === 'awaiting_buyer') return t('awaitingBuyer')
  if (status === 'awaiting_supplier') return t('awaitingSupplier')
  if (status === 'agreed') return t('agreed')
  return status.replaceAll('_', ' ')
}

export function QuotesPage({ session }: { session: Session }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const buyer = session.roles.includes('buyer')
  const [activeId, setActiveId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [counterOpen, setCounterOpen] = useState(false)
  const [counterDraft, setCounterDraft] = useState<CounterDraft>()
  const list = useQuery({ queryKey: ['negotiations'], queryFn: () => api<{ items: Quote[] }>('/api/negotiations') })
  const selectedId = activeId || list.data?.items[0]?.id || ''
  const detail = useQuery({
    queryKey: ['negotiation', selectedId],
    queryFn: () => api<NegotiationDetail>(`/api/quotations/${selectedId}`),
    enabled: !!selectedId,
  })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['negotiations'] }),
      queryClient.invalidateQueries({ queryKey: ['negotiation', selectedId] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
  }

  const transition = useMutation({
    mutationFn: ({ action, body }: { action: string; body: object }) => api(`/api/quotations/${selectedId}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: async () => { toast.success('Negotiation updated'); setCounterOpen(false); setCounterDraft(undefined); await refresh() },
    onError: (error: Error) => toast.error(error.message),
  })
  const sendMessage = useMutation({
    mutationFn: (body: string) => api(`/api/quotations/${selectedId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body, client_message_id: crypto.randomUUID() }),
    }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['negotiation', selectedId] }) },
    onError: (error: Error) => toast.error(error.message),
  })
  const confirm = useMutation({
    mutationFn: () => {
      const quotes = list.data!.items.filter((item) => selected.includes(item.id))
      return api<{ orders: unknown[] }>(`/api/requirements/${quotes[0].requirement.id}/confirm`, {
        method: 'POST', body: JSON.stringify({ quotation_ids: selected }), idempotencyKey: makeIdempotencyKey('confirm'),
      })
    },
    onSuccess: async (response) => { toast.success(`${response.orders.length} supplier order(s) confirmed and stock reserved`); setSelected([]); await refresh() },
    onError: (error: Error) => toast.error(error.message),
  })

  const toggleSelected = (quote: Quote, checked: boolean) => {
    if (!checked) return setSelected((items) => items.filter((id) => id !== quote.id))
    const first = list.data?.items.find((item) => selected.includes(item.id))
    if (first && first.requirement.id !== quote.requirement.id) {
      toast.error('Select offers for one buyer requirement at a time.')
      return
    }
    setSelected((items) => [...items, quote.id])
  }

  const active = detail.data
  return (
    <>
      <PageTitle
        title={t('negotiationTitle')}
        description={t('negotiationHelp')}
        actions={buyer && selected.length ? <Button disabled={confirm.isPending} onClick={() => confirm.mutate()}>{confirm.isPending ? <Loader2 className="animate-spin" /> : <PackageCheck />}Confirm {selected.length} selected</Button> : undefined}
      />
      {list.isLoading ? <LoadingPage /> : list.error ? <ErrorState error={list.error} retry={() => void list.refetch()} /> : !list.data?.items.length ? (
        <EmptyState icon={HandCoins} title={t('noNegotiations')} body={t('noNegotiationsHelp')} />
      ) : (
        <div className="grid min-w-0 gap-5 lg:grid-cols-[330px_minmax(0,1fr)]">
          <section aria-label="Negotiation list" className="space-y-3">
            {list.data.items.map((quote) => {
              const confirmable = buyer && quote.actions.can_confirm_order
              return (
                <Card key={quote.id} className={`cursor-pointer transition-colors ${selectedId === quote.id ? 'border-primary ring-1 ring-primary' : 'hover:border-primary/50'}`} onClick={() => { setActiveId(quote.id); window.setTimeout(() => document.getElementById('negotiation-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50) }}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate font-semibold">{quote.supplier.name}</p><p className="text-sm text-muted-foreground">{quote.requirement.crop} · {quote.revision.quantity_kg} kg</p></div><StatusBadge status={quote.status} /></div>
                    <div className="mt-3 flex items-end justify-between"><div><p className="font-semibold">₹{quote.revision.price_inr_per_kg}/kg</p><p className="text-xs text-muted-foreground">{shortDate(quote.revision.delivery_date)}</p></div><ArrowRight className="size-4 text-muted-foreground" /></div>
                    {confirmable && <label className="mt-3 flex min-h-11 items-center gap-3 border-t pt-3" onClick={(event) => event.stopPropagation()}><input type="checkbox" className="size-5 accent-primary" checked={selected.includes(quote.id)} onChange={(event) => toggleSelected(quote, event.target.checked)} /><span className="text-sm font-medium">Select to confirm</span></label>}
                  </CardContent>
                </Card>
              )
            })}
          </section>

          <section id="negotiation-detail" className="min-w-0 scroll-mt-20">
            {detail.isLoading ? <LoadingPage /> : detail.error ? <ErrorState error={detail.error} retry={() => void detail.refetch()} /> : active ? (
              <div className="space-y-4">
                <Card>
                  <CardHeader>
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div><CardTitle>{active.requirement.crop} with {active.supplier.name}</CardTitle><CardDescription>{active.requirement.quantity_kg} kg needed in {active.requirement.destination} by {shortDate(active.requirement.delivery_deadline)}</CardDescription></div>
                      <div className="flex flex-wrap gap-2">
                        {buyer && <Suspense fallback={null}><ProcurementAssistant key={active.id} quotationId={active.id} requirementId={active.requirement.id} onUseDraft={(draft) => { setCounterDraft(draft); setCounterOpen(true) }} trigger={<Button variant="outline"><Bot />{t('draftCounter')}</Button>} /></Suspense>}
                        {active.actions.can_counter && <Button onClick={() => { setCounterDraft(undefined); setCounterOpen(true) }}>{t('counterOffer')}</Button>}
                        {active.actions.can_accept_terms && <Button onClick={() => transition.mutate({ action: 'accept-terms', body: { version: active.version } })}><Check />{t('acceptTerms')}</Button>}
                        {active.actions.can_reject && <Button variant="destructive" onClick={() => transition.mutate({ action: 'reject', body: { version: active.version } })}><X />{t('reject')}</Button>}
                        {active.actions.can_withdraw && <Button variant="outline" onClick={() => transition.mutate({ action: 'withdraw', body: { version: active.version } })}>{t('withdraw')}</Button>}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <Alert className="mb-4 border-amber-300 bg-amber-50"><AlertDescription>{t('noStockReserved')}</AlertDescription></Alert>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <Metric label="Status" value={statusText(active.status, t)} />
                      <Metric label="Offered quantity" value={`${active.revision.quantity_kg} kg`} />
                      <Metric label="Price" value={`₹${active.revision.price_inr_per_kg}/kg`} />
                      <Metric label="Total" value={inr(active.revision.total_paise)} />
                    </div>
                  </CardContent>
                </Card>

                <Tabs defaultValue="history">
                  <TabsList className="h-11 w-full sm:w-auto"><TabsTrigger value="history" className="px-4"><HandCoins />{t('offerHistory')}</TabsTrigger><TabsTrigger value="messages" className="px-4"><MessageSquare />{t('privateChat')}</TabsTrigger></TabsList>
                  <TabsContent value="history" className="space-y-3">
                    {[...active.revisions].reverse().map((revision) => (
                      <Card key={revision.id}><CardContent className="p-4 sm:p-5"><div className="flex flex-col justify-between gap-3 sm:flex-row"><div><p className="font-semibold">Revision {revision.number} · {revision.actor.name}</p><p className="text-sm text-muted-foreground">{revision.actor_organization?.name} · {dateTime(revision.created_at)}</p></div><div className="text-left sm:text-right"><p className="font-semibold">{revision.quantity_kg} kg at ₹{revision.price_inr_per_kg}/kg</p><p className="text-sm text-muted-foreground">Grade {revision.quality_grade} · {shortDate(revision.delivery_date)}</p></div></div><p className="mt-3 text-sm"><b>{revision.delivery_mode === 'seller_delivery' ? 'Seller delivery' : 'Buyer pickup'}</b>{revision.delivery_charge_paise ? ` · ₹${revision.delivery_charge_inr} delivery charge` : ''}<br />{revision.delivery_terms}</p>{revision.note && <p className="mt-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">{revision.note}</p>}<div className="mt-3 flex flex-wrap gap-2">{revision.allocations.map((allocation) => <span key={allocation.id} className="rounded-full border px-3 py-1 text-xs">{allocation.farmer.name}: {allocation.quantity_kg} kg</span>)}</div></CardContent></Card>
                    ))}
                  </TabsContent>
                  <TabsContent value="messages">
                      <Card><CardContent className="p-4 sm:p-5"><div className="max-h-[420px] space-y-3 overflow-y-auto" aria-live="polite">{active.messages.length ? active.messages.map((message) => <div key={message.id} className={`flex ${message.mine ? 'justify-end' : 'justify-start'}`}><div className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${message.mine ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}><p>{message.body}</p><p className={`mt-1 text-xs ${message.mine ? 'text-white/70' : 'text-muted-foreground'}`}>{message.author.name} · {dateTime(message.created_at)}</p></div></div>) : <p className="py-10 text-center text-sm text-muted-foreground">No messages yet. Start a private conversation about this offer.</p>}</div>{active.actions.can_message && <MessageForm pending={sendMessage.isPending} onSend={(body) => sendMessage.mutate(body)} />}</CardContent></Card>
                  </TabsContent>
                </Tabs>
              </div>
            ) : null}
          </section>
        </div>
      )}

      <Dialog open={counterOpen} onOpenChange={setCounterOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{t('counterOffer')}</DialogTitle><DialogDescription>Propose clear commercial terms. This does not reserve produce.</DialogDescription></DialogHeader>
          {active && <CounterForm key={`${active.id}-${JSON.stringify(counterDraft)}`} quote={active} draft={counterDraft} pending={transition.isPending} onSubmit={(body) => transition.mutate({ action: 'counter', body })} />}
        </DialogContent>
      </Dialog>
    </>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-semibold capitalize">{value}</p></div>
}

function MessageForm({ pending, onSend }: { pending: boolean; onSend: (body: string) => void }) {
  const { t } = useTranslation()
  const [body, setBody] = useState('')
  return <form className="mt-4 flex gap-2 border-t pt-4" onSubmit={(event) => { event.preventDefault(); if (!body.trim()) return; onSend(body.trim()); setBody('') }}><Input value={body} onChange={(event) => setBody(event.target.value)} maxLength={2000} placeholder={t('messagePlaceholder')} aria-label={t('messagePlaceholder')} /><Button size="icon" disabled={pending || !body.trim()} aria-label={t('sendMessage')}>{pending ? <Loader2 className="animate-spin" /> : <Send />}</Button></form>
}

function CounterForm({ quote, draft, pending, onSubmit }: { quote: NegotiationDetail; draft?: CounterDraft; pending: boolean; onSubmit: (body: object) => void }) {
  const revision = quote.revision
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const body: Record<string, unknown> = {
      version: quote.version,
      quantity_kg: form.get('quantity'),
      price_inr_per_kg: form.get('price'),
      quality_grade: form.get('quality'),
      delivery_date: form.get('date'),
      delivery_terms: form.get('terms'),
      note: form.get('note'),
    }
    if (quote.side === 'supplier') {
      body.allocations = revision.allocations.map((allocation) => ({
        produce_lot_id: allocation.lot.id,
        quantity_kg: form.get(`allocation-${allocation.id}`),
      }))
    }
    onSubmit(body)
  }
  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Quantity (kg)"><Input aria-label="Counteroffer quantity in kilograms" name="quantity" type="number" min="0.001" step="0.001" max={quote.side === 'buyer' ? revision.quantity_kg : undefined} defaultValue={draft?.quantity_kg ?? revision.quantity_kg} required /></Field>
        <Field label="Price (₹/kg)"><Input aria-label="Counteroffer price in INR per kilogram" name="price" type="number" min="0.01" step="0.01" defaultValue={draft?.price_inr_per_kg ?? revision.price_inr_per_kg} required /></Field>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Quality grade"><Select name="quality" defaultValue={draft?.quality_grade ?? revision.quality_grade}><SelectTrigger aria-label="Counteroffer quality grade"><SelectValue /></SelectTrigger><SelectContent>{['A', 'B', 'C'].map((grade) => <SelectItem key={grade} value={grade}>Grade {grade}</SelectItem>)}</SelectContent></Select></Field>
        <Field label="Delivery date"><Input aria-label="Counteroffer delivery date" name="date" type="date" max={quote.requirement.delivery_deadline} defaultValue={draft?.delivery_date ?? revision.delivery_date} required /></Field>
      </div>
      <Field label="Delivery terms"><Input aria-label="Counteroffer delivery terms" name="terms" maxLength={2000} defaultValue={draft?.delivery_terms ?? revision.delivery_terms} required /></Field>
      <Field label="Note"><Textarea aria-label="Counteroffer note" name="note" maxLength={2000} defaultValue={draft?.note ?? draft?.notes ?? revision.note} /></Field>
      {quote.side === 'supplier' && <div className="space-y-3 rounded-xl border p-4"><p className="text-sm font-medium">Produce allocations</p>{revision.allocations.map((allocation) => <Field key={allocation.id} label={`${allocation.farmer.name} · ${allocation.lot.crop}`}><Input aria-label={`${allocation.farmer.name} allocation in kilograms`} name={`allocation-${allocation.id}`} type="number" min="0.001" step="0.001" max={allocation.lot.available_quantity_kg} defaultValue={allocation.quantity_kg} required /></Field>)}</div>}
      <Button className="w-full" disabled={pending}>{pending && <Loader2 className="animate-spin" />}Send counteroffer</Button>
    </form>
  )
}
