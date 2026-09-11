import { lazy, Suspense, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Controller, useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { Bot, Boxes, ClipboardList, FileDown, HandCoins, PackageOpen, Search } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { EmptyState, ErrorState, Field, LoadingPage, PageTitle, StatusBadge, daysFromNow, shortDate } from '@/components/common'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import type { DeliveryMode, Lot, ProcurementDraft, Requirement, Session } from '@/lib/types'

type Match = { lot: Lot; supplier: { id: string; name: string; rating_summary?: { average_rating: number; review_count: number } }; score: number; explanations: string[] }
type AllocationPreview = { allocations: { suggested_quantity_kg: number }[]; shortfall_kg: number }
type EligibleLots = {
  items: Lot[]
  remaining_requirement_kg: number
  existing_negotiations: { id: string; supplier_organization_id: string; status: string }[]
}
const ProcurementAssistant = lazy(() => import('@/components/ProcurementAssistant'))

const quoteSchema = z.object({
  lotId: z.string().min(1, 'Choose a produce lot.'),
  quantity: z.string().trim().refine((value) => Number.isFinite(Number(value)) && Number(value) > 0, 'Enter a quantity greater than zero.'),
  price: z.string().trim().regex(/^\d+(?:\.\d{1,2})?$/, 'Enter a positive price with up to two decimal places.').refine((value) => Number(value) > 0, 'Enter a price greater than zero.'),
  date: z.string().min(1, 'Choose a delivery date.'),
  terms: z.string().trim().min(1, 'Enter delivery terms.').max(500, 'Delivery terms must be 500 characters or fewer.'),
  note: z.string().max(1000, 'The note must be 1,000 characters or fewer.'),
})
type QuoteValues = z.infer<typeof quoteSchema>

export function RequirementsPage({ session }: { session: Session }) {
  const buyer = session.roles.includes('buyer')
  const supplier = session.roles.some((role) => role === 'farmer' || role === 'fpo_manager')
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ProcurementDraft>()
  const [selected, setSelected] = useState<Requirement>()
  const [quoteFor, setQuoteFor] = useState<Requirement>()
  const requirements = useQuery({ queryKey: ['requirements', buyer], queryFn: () => api<{ items: Requirement[] }>(`/api/requirements${buyer ? '?mine=true' : ''}`) })
  const matches = useQuery({ queryKey: ['matches', selected?.id], queryFn: () => api<{ items: Match[] }>(`/api/requirements/${selected!.id}/matches`), enabled: !!selected })
  const allocation = useQuery({ queryKey: ['allocation', selected?.id], queryFn: () => api<AllocationPreview>(`/api/requirements/${selected!.id}/allocation-preview`), enabled: !!selected })

  useEffect(() => {
    const saved = localStorage.getItem('agrilink-requirement-draft')
    if (!saved) return
    try {
      setDraft(JSON.parse(saved) as ProcurementDraft)
      setOpen(true)
    } finally {
      localStorage.removeItem('agrilink-requirement-draft')
    }
  }, [])

  const create = useMutation({
    mutationFn: (body: object) => api('/api/requirements', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: async () => { toast.success('Requirement posted'); setOpen(false); setDraft(undefined); await queryClient.invalidateQueries({ queryKey: ['requirements'] }) },
    onError: (error: Error) => toast.error(error.message),
  })
  const createRequirement = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    create.mutate({ crop: form.get('crop'), variety: form.get('variety'), quantity_kg: form.get('quantity'), acceptable_quality: form.get('quality'), destination: form.get('destination'), delivery_deadline: form.get('deadline'), delivery_mode: form.get('delivery_mode'), budget_price_inr: form.get('budget'), notes: form.get('notes') })
  }

  return (
    <>
      <PageTitle
        title={buyer ? 'Procurement requirements' : 'Buyer demand board'}
        description={buyer ? 'Describe what you need, compare deterministic supplier matches, and combine supply.' : 'Find compatible demand and send a clear commercial offer.'}
        actions={<>
          {buyer && <Suspense fallback={null}><ProcurementAssistant trigger={<Button variant="outline"><Bot />Draft with AI</Button>} /></Suspense>}
          {buyer && <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button><ClipboardList />Post requirement</Button></DialogTrigger><DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>New procurement requirement</DialogTitle><DialogDescription>Use kilograms and INR per kilogram. Budget is optional.</DialogDescription></DialogHeader><RequirementForm draft={draft} submit={createRequirement} pending={create.isPending} /></DialogContent></Dialog>}
          {buyer && <Button asChild variant="outline"><a href="/api/requirements/export.csv"><FileDown />CSV</a></Button>}
        </>}
      />
      {requirements.isLoading ? <LoadingPage /> : requirements.error ? <ErrorState error={requirements.error} retry={() => void requirements.refetch()} /> : !requirements.data?.items.length ? <EmptyState title="No requirements" body="Post a procurement requirement to begin supplier discovery." /> : (
        <div className="grid gap-4">
          {requirements.data.items.map((requirement) => <Card key={requirement.id}><CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center"><div className="flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-lg font-semibold">{requirement.quantity_kg.toLocaleString()} kg {requirement.crop}</h3><StatusBadge status={requirement.status} /><Badge variant="outline">{requirement.delivery_mode === 'seller_delivery' ? 'Delivery Required' : 'Buyer Pickup'}</Badge></div><p className="text-sm text-muted-foreground">{requirement.variety || 'Any variety'} · Grade {requirement.acceptable_quality} or better · {requirement.destination}</p><p className="mt-2 text-sm">Due <b>{shortDate(requirement.delivery_deadline)}</b> · {requirement.budget_price_inr ? `Up to ₹${requirement.budget_price_inr}/kg` : 'Budget open'}</p></div><div className="flex flex-wrap gap-2">{buyer && <><Suspense fallback={null}><ProcurementAssistant requirementId={requirement.id} trigger={<Button variant="ghost"><Bot />Analyze</Button>} /></Suspense><Button variant="outline" onClick={() => setSelected(requirement)}><Search />Matches</Button></>}{supplier && <Button onClick={() => setQuoteFor(requirement)}><HandCoins />Send offer</Button>}</div></CardContent></Card>)}
        </div>
      )}

      <Dialog open={!!selected} onOpenChange={(value) => !value && setSelected(undefined)}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>Explainable supplier matching</DialogTitle><DialogDescription>Deterministic score: quantity coverage 50%, price fit 30%, delivery fit 20%. This is not a trained AI model.</DialogDescription></DialogHeader>{matches.isLoading ? <Skeleton className="h-60" /> : <div className="space-y-3">{allocation.data && <Alert><Boxes /><AlertTitle>Suggested allocation · preview only</AlertTitle><AlertDescription>{allocation.data.allocations.map((item) => `${item.suggested_quantity_kg} kg`).join(' + ')}{allocation.data.shortfall_kg > 0 && ` · ${allocation.data.shortfall_kg} kg shortfall`}. No stock is reserved.</AlertDescription></Alert>}{matches.data?.items.map((match) => <div key={match.lot.id} className="rounded-xl border p-4"><div className="flex justify-between gap-3"><div><b>{match.supplier.name}</b><p className="text-sm text-muted-foreground">{match.lot.available_quantity_kg} kg · ₹{match.lot.asking_price_inr}/kg</p>{match.supplier.rating_summary?.review_count ? <a className="text-sm font-medium text-[#8a5b00] hover:underline" href={`/reviews?supplier=${match.supplier.id}`}>★ {match.supplier.rating_summary.average_rating} · {match.supplier.rating_summary.review_count} reviews</a> : <p className="text-xs text-muted-foreground">No reviews yet</p>}</div><Badge>{match.score}/100</Badge></div><Progress className="my-3" value={match.score} />{match.explanations.map((explanation) => <p key={explanation} className="text-sm text-muted-foreground">• {explanation}</p>)}</div>)}</div>}</DialogContent>
      </Dialog>

      <Dialog open={!!quoteFor} onOpenChange={(value) => !value && setQuoteFor(undefined)}>
        <DialogContent className="max-h-[92vh] w-[calc(100vw-2rem)] max-w-[calc(100vw-2rem)] overflow-x-hidden overflow-y-auto sm:max-w-xl"><DialogHeader className="min-w-0"><DialogTitle className="break-words pr-8">Offer for {quoteFor?.crop}</DialogTitle><DialogDescription>Your commercial terms and future counteroffers remain in the negotiation history.</DialogDescription></DialogHeader>{quoteFor && <QuoteForm requirement={quoteFor} done={() => { setQuoteFor(undefined); void queryClient.invalidateQueries({ queryKey: ['negotiations'] }) }} />}</DialogContent>
      </Dialog>
    </>
  )
}

function RequirementForm({ submit, pending, draft }: { submit: (event: FormEvent<HTMLFormElement>) => void; pending: boolean; draft?: ProcurementDraft }) {
  const [mode, setMode] = useState<DeliveryMode>(draft?.delivery_mode ?? 'seller_delivery')
  return <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2"><Field label="Crop"><Input name="crop" defaultValue={draft?.crop ?? 'Tomato'} required /></Field><Field label="Variety"><Input name="variety" defaultValue={draft?.variety ?? 'Arka Rakshak'} /></Field><Field label="Quantity (kg)"><Input name="quantity" type="number" min="0.001" step="0.001" defaultValue={draft?.quantity_kg ?? 1000} required /></Field><Field label="Acceptable quality"><Select name="quality" defaultValue={draft?.acceptable_quality ?? 'B'}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{['A', 'B', 'C'].map((grade) => <SelectItem key={grade} value={grade}>Grade {grade} or better</SelectItem>)}</SelectContent></Select></Field><Field label="Delivery mode"><Select name="delivery_mode" value={mode} onValueChange={(value) => setMode(value as DeliveryMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="buyer_pickup">Buyer Pickup</SelectItem><SelectItem value="seller_delivery">Delivery Required</SelectItem></SelectContent></Select></Field><Field label={mode === 'seller_delivery' ? 'Delivery location' : 'Pickup location'}><Input name="destination" defaultValue={draft?.destination ?? 'Vijayawada, Andhra Pradesh'} required /></Field><Field label={mode === 'seller_delivery' ? 'Required delivery date' : 'Pickup-by date'}><Input name="deadline" type="date" defaultValue={draft?.delivery_deadline ?? daysFromNow(14)} required /></Field><Field label="Budget (₹/kg)"><Input name="budget" type="number" min="0.01" step="0.01" defaultValue={draft?.budget_price_inr ?? 25} /></Field><Field label="Additional notes" className="sm:col-span-2"><Textarea name="notes" defaultValue={draft?.notes} /></Field><Button className="sm:col-span-2" disabled={pending}>Post requirement</Button></form>
}

function QuoteForm({ requirement, done }: { requirement: Requirement; done: () => void }) {
  const { t } = useTranslation()
  const lots = useQuery({
    queryKey: ['eligible-lots', requirement.id],
    queryFn: () => api<EligibleLots>(`/api/requirements/${requirement.id}/eligible-lots`),
  })
  if (lots.isLoading) return <div className="space-y-3" aria-label={t('loadingLots')}><Skeleton className="h-11 w-full" /><Skeleton className="h-24 w-full" /><Skeleton className="h-11 w-full" /></div>
  if (lots.error) return <ErrorState error={lots.error} retry={() => void lots.refetch()} />
  if (!lots.data?.items.length) return <EmptyState icon={PackageOpen} title={t('noCompatibleLots')} body={t('noCompatibleLotsHelp')} action={<Button asChild><Link to="/produce">{t('addProduce')}</Link></Button>} />
  return <ReadyQuoteForm requirement={requirement} data={lots.data} done={done} />
}

function ReadyQuoteForm({ requirement, data, done }: { requirement: Requirement; data: EligibleLots; done: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const initialLot = data.items[0]
  const suggestedQuantity = Math.min(initialLot.available_quantity_kg, data.remaining_requirement_kg)
  const form = useForm<QuoteValues>({
    resolver: zodResolver(quoteSchema),
    defaultValues: {
      lotId: initialLot.id,
      quantity: String(suggestedQuantity),
      price: String(initialLot.asking_price_inr),
      date: requirement.delivery_deadline,
      terms: 'Supplier delivery in ventilated crates',
      note: '',
    },
  })
  const [selectedLotId, setSelectedLotId] = useState(initialLot.id)
  const lot = data.items.find((item) => item.id === selectedLotId) ?? initialLot
  const existingNegotiation = data.existing_negotiations.find((item) => item.supplier_organization_id === lot.farmer_organization_id)
  const waitingOnBuyer = existingNegotiation && ['awaiting_buyer', 'agreed', 'accepted'].includes(existingNegotiation.status)
  const submit = useMutation({
    mutationFn: (body: object) => api(`/api/requirements/${requirement.id}/quotations`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: async () => {
      toast.success(t('offerSent'))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['negotiations'] }),
        queryClient.invalidateQueries({ queryKey: ['requirements'] }),
        queryClient.invalidateQueries({ queryKey: ['produce'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
      done()
    },
    onError: (error: Error) => {
      form.setError('root', { message: error.message })
      toast.error(error.message)
    },
  })
  const submitOffer = form.handleSubmit((values) => {
    if (Number(values.quantity) > lot.available_quantity_kg) {
      form.setError('quantity', { message: t('quantityAvailableError', { quantity: lot.available_quantity_kg }) })
      return
    }
    if (Number(values.quantity) > data.remaining_requirement_kg) {
      form.setError('quantity', { message: t('quantityRemainingError', { quantity: data.remaining_requirement_kg }) })
      return
    }
    submit.mutate({
      allocations: [{ produce_lot_id: values.lotId, quantity_kg: values.quantity }],
      price_inr_per_kg: values.price,
      delivery_date: values.date,
      delivery_terms: values.terms,
      note: values.note,
    })
  })
  return <form className="min-w-0 space-y-4" noValidate onSubmit={submitOffer}>
    <Field label={t('yourProduceLot')}>
      <Controller control={form.control} name="lotId" render={({ field }) => <Select value={field.value} onValueChange={(value) => {
        field.onChange(value)
        setSelectedLotId(value)
        const nextLot = data.items.find((item) => item.id === value)
        if (nextLot) {
          form.setValue('quantity', String(Math.min(nextLot.available_quantity_kg, data.remaining_requirement_kg)), { shouldValidate: true })
          form.setValue('price', String(nextLot.asking_price_inr), { shouldValidate: true })
        }
        form.clearErrors('root')
      }}><SelectTrigger aria-label={t('yourProduceLot')} className="min-h-11 w-full min-w-0 overflow-hidden [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate"><SelectValue placeholder={t('chooseLot')} /></SelectTrigger><SelectContent position="popper" className="max-w-[calc(100vw-2rem)]">{data.items.map((item) => <SelectItem key={item.id} value={item.id}>{item.crop} · {item.available_quantity_kg} kg {t('available')}</SelectItem>)}</SelectContent></Select>} />
      {form.formState.errors.lotId && <p className="text-sm text-destructive" role="alert">{form.formState.errors.lotId.message}</p>}
    </Field>
    {waitingOnBuyer && <Alert><HandCoins /><AlertTitle>{t('offerAlreadySent')}</AlertTitle><AlertDescription className="space-y-3"><p>{t('offerAlreadySentHelp')}</p><Button asChild size="sm" variant="outline"><Link to={`/negotiations/${existingNegotiation.id}`}>{t('viewNegotiation')}</Link></Button></AlertDescription></Alert>}
    {!waitingOnBuyer && <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={t('quantity')}><Input aria-label={t('quantity')} type="number" inputMode="decimal" step="0.001" max={Math.min(lot.available_quantity_kg, data.remaining_requirement_kg)} min="0.001" {...form.register('quantity')} />{form.formState.errors.quantity && <p className="text-sm text-destructive" role="alert">{form.formState.errors.quantity.message}</p>}</Field>
        <Field label={t('price')}><Input aria-label={t('price')} type="number" inputMode="decimal" step="0.01" min="0.01" {...form.register('price')} />{form.formState.errors.price && <p className="text-sm text-destructive" role="alert">{form.formState.errors.price.message}</p>}</Field>
      </div>
      <p className="text-sm text-muted-foreground">{t('offerLimits', { available: lot.available_quantity_kg, remaining: data.remaining_requirement_kg })}</p>
      <Field label={t('deliveryDate')}><Input aria-label={t('deliveryDate')} type="date" min={new Date().toISOString().slice(0, 10)} max={requirement.delivery_deadline} {...form.register('date')} />{form.formState.errors.date && <p className="text-sm text-destructive" role="alert">{form.formState.errors.date.message}</p>}</Field>
      <Field label={t('deliveryTerms')}><Input aria-label={t('deliveryTerms')} {...form.register('terms')} />{form.formState.errors.terms && <p className="text-sm text-destructive" role="alert">{form.formState.errors.terms.message}</p>}</Field>
      <Field label={t('notes')}><Textarea aria-label={t('notes')} {...form.register('note')} />{form.formState.errors.note && <p className="text-sm text-destructive" role="alert">{form.formState.errors.note.message}</p>}</Field>
      {form.formState.errors.root?.message && <Alert variant="destructive"><AlertTitle>{t('offerNotSent')}</AlertTitle><AlertDescription>{form.formState.errors.root.message}</AlertDescription></Alert>}
      <Button className="min-h-11 w-full" disabled={submit.isPending} aria-busy={submit.isPending}>{submit.isPending ? t('sendingOffer') : existingNegotiation ? t('sendRevisedOffer') : t('submitQuote')}</Button>
    </>}
  </form>
}
