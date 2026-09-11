import { useMemo, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquareText, Pencil, Star } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { EmptyState, ErrorState, LoadingPage, PageTitle, shortDate } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import type { Order, RatingSummary, Review, Session } from '@/lib/types'

type RatingsResponse = { organization: { id: string; name: string; type: string }; summary: RatingSummary; items: Review[] }
type Draft = { supplier_id: string; supplier_name: string; reviewed_role: 'supplier'|'fpo'; overall_rating: number; quality_rating: number; delivery_rating: number; communication_rating: number; comment: string; version?: number }

function Stars({ value, setValue, label }: { value: number; setValue: (value: number) => void; label: string }) {
  return <fieldset><legend className="mb-2 text-sm font-medium">{label}</legend><div className="flex gap-1" role="radiogroup" aria-label={label}>{[1,2,3,4,5].map((score) => <button key={score} type="button" role="radio" aria-checked={value === score} aria-label={`${score} ${score === 1 ? 'star' : 'stars'}`} onClick={() => setValue(score)} className="flex size-11 items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><Star className={`size-7 ${score <= value ? 'fill-[#F2B84B] text-[#8a5b00]' : 'text-muted-foreground/40'}`} /></button>)}</div></fieldset>
}

function ReviewCard({ review }: { review: Review }) {
  const { t } = useTranslation()
  return <Card><CardContent className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><b>{review.supplier_name}</b><Badge variant="outline" className="capitalize">{review.reviewed_role}</Badge></div><p className="text-sm text-muted-foreground">{review.order_number} · {review.order.crops.join(', ')} · {review.order.quantity_kg} kg</p></div><div className="flex items-center gap-1 font-semibold text-[#8a5b00]"><Star className="size-4 fill-[#F2B84B]" />{review.overall_rating}/5</div></div>{review.comment ? <p className="mt-4 text-sm">{review.comment}</p> : <p className="mt-4 text-sm text-muted-foreground">{t('noWrittenFeedback')}</p>}<div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs text-muted-foreground"><span>{t('qualityShort')} <b className="block text-foreground">{review.quality_rating}/5</b></span><span>{t('deliveryShort')} <b className="block text-foreground">{review.delivery_rating}/5</b></span><span>{t('communicationShort')} <b className="block text-foreground">{review.communication_rating}/5</b></span></div><p className="mt-4 text-xs text-muted-foreground">{review.buyer_label} · {shortDate(review.updated_at)}</p></CardContent></Card>
}

function SupplierReviewSummary({ data }: { data: RatingsResponse }) {
  const { t } = useTranslation()
  const dimensions = [[t('qualityShort'), data.summary.quality_rating], [t('deliveryShort'), data.summary.delivery_rating], [t('communicationShort'), data.summary.communication_rating]] as const
  return <section><Card className="mb-4"><CardContent className="grid gap-4 p-5 sm:grid-cols-5"><div className="sm:col-span-2"><h2 className="font-semibold">{data.organization.name}</h2><p className="mt-1 text-3xl font-semibold text-primary">{data.summary.average_rating || '—'} <span className="text-base">/ 5</span></p><p className="text-sm text-muted-foreground">{data.summary.review_count} {t('reviews')}</p></div>{dimensions.map(([label,value])=><div key={label} className="rounded-xl bg-muted p-3 text-sm"><span className="text-muted-foreground">{label}</span><b className="mt-1 block">{Number(value)||'—'}/5</b></div>)}</CardContent></Card>{data.items.length ? <div className="grid gap-4 md:grid-cols-2">{data.items.map((review)=><ReviewCard key={review.review_id} review={review}/>)}</div> : <EmptyState icon={Star} title={t('noReviews')} body={t('supplierNoReviews')} />}</section>
}

function reviewDrafts(order: Order): Draft[] {
  const parties = [order.supplier, order.coordinating_fpo].filter(Boolean) as NonNullable<Order['supplier']>[]
  return parties.map((party, index) => {
    const existing = order.reviews.find((item) => item.supplier_id === party.id)
    return { supplier_id: party.id, supplier_name: party.name, reviewed_role: index === 0 ? 'supplier' : 'fpo', overall_rating: existing?.overall_rating ?? 5, quality_rating: existing?.quality_rating ?? 5, delivery_rating: existing?.delivery_rating ?? 5, communication_rating: existing?.communication_rating ?? 5, comment: existing?.comment ?? '', version: existing?.version }
  })
}

function ReviewDialog({ order, close }: { order: Order; close: () => void }) {
  const qc = useQueryClient(); const { t } = useTranslation()
  const [drafts, setDrafts] = useState<Draft[]>(() => reviewDrafts(order))
  const save = useMutation({ mutationFn: () => api(`/api/orders/${order.id}/reviews`, { method: order.reviews.length ? 'PATCH' : 'POST', body: JSON.stringify({ reviews: drafts }) }), onSuccess: async () => { toast.success(t('reviewSaved')); await Promise.all([qc.invalidateQueries({queryKey:['orders']}), qc.invalidateQueries({queryKey:['my-reviews']}), qc.invalidateQueries({queryKey:['organization-reviews']})]); close() }, onError: (error: Error) => toast.error(error.message) })
  const update = (index: number, key: keyof Draft, value: string|number) => setDrafts((items) => items.map((item, itemIndex) => itemIndex === index ? {...item, [key]: value} : item))
  return <Dialog open onOpenChange={(value) => !value && close()}><DialogContent className="max-h-[92vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>{order.reviews.length ? t('editFeedback') : t('rateSupplier')}</DialogTitle><DialogDescription>{`${order.order_number} · ${order.lines.map((line) => `${line.crop} ${line.agreed_quantity_kg} kg`).join(', ')} · ${shortDate(order.delivery_deadline)}`}</DialogDescription></DialogHeader><form className="space-y-6" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>{drafts.map((draft, index) => <section key={draft.supplier_id} className="space-y-4 rounded-2xl border p-4"><div><h3 className="font-semibold">{draft.supplier_name}</h3><p className="text-sm capitalize text-muted-foreground">{draft.reviewed_role === 'fpo' ? t('coordinatingFpo') : t('supplyingFarmer')}</p></div><div className="grid gap-4 sm:grid-cols-2"><Stars label={t('overallRating')} value={draft.overall_rating} setValue={(value) => update(index,'overall_rating',value)} /><Stars label={t('qualityRating')} value={draft.quality_rating} setValue={(value) => update(index,'quality_rating',value)} /><Stars label={t('deliveryRating')} value={draft.delivery_rating} setValue={(value) => update(index,'delivery_rating',value)} /><Stars label={t('communicationRating')} value={draft.communication_rating} setValue={(value) => update(index,'communication_rating',value)} /></div><div className="space-y-2"><Label htmlFor={`comment-${draft.supplier_id}`}>{t('optionalFeedback')}</Label><Textarea id={`comment-${draft.supplier_id}`} value={draft.comment} maxLength={1000} onChange={(event) => update(index,'comment',event.target.value)} /><p className="text-right text-xs text-muted-foreground">{draft.comment.length}/1000</p></div></section>)}<Button className="w-full" disabled={save.isPending || !drafts.length}>{save.isPending ? t('saving') : t('submitReview')}</Button></form></DialogContent></Dialog>
}

export function ReviewsPage({ session }: { session: Session }) {
  const { t } = useTranslation(); const buyer = session.roles.includes('buyer'); const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.search).get('order') || '')
  const selectedSupplierId = new URLSearchParams(window.location.search).get('supplier') || ''
  const orders = useQuery({ queryKey:['orders'], queryFn:()=>api<{items:Order[]}>('/api/orders'), enabled:buyer })
  const mine = useQuery({ queryKey:['my-reviews'], queryFn:()=>api<{items:Review[]}>('/api/reviews/mine'), enabled:buyer })
  const selectedSupplier = useQuery({ queryKey:['organization-reviews',selectedSupplierId], queryFn:()=>api<RatingsResponse>(`/api/organizations/${selectedSupplierId}/reviews`), enabled:buyer&&!!selectedSupplierId })
  const supplierMemberships = session.memberships.filter((item) => ['farmer','fpo_manager'].includes(item.role))
  const ratingQueries = useQueries({ queries: supplierMemberships.map((item) => ({ queryKey:['organization-reviews',item.organization.id], queryFn:()=>api<RatingsResponse>(`/api/organizations/${item.organization.id}/reviews`) })) })
  const eligible = useMemo(() => orders.data?.items.filter((item) => item.review_eligible) ?? [], [orders.data])
  const selected = eligible.find((item) => item.id === selectedId)
  if (buyer) return <><PageTitle title={t('reviewFeedback')} description={t('reviewHelp')} />{orders.isLoading || mine.isLoading ? <LoadingPage/> : orders.error ? <ErrorState error={orders.error} retry={()=>void orders.refetch()}/> : <div className="space-y-8">{selectedSupplierId ? <section><h2 className="mb-3 text-lg font-semibold">{t('supplierProfile')}</h2>{selectedSupplier.isLoading ? <LoadingPage/> : selectedSupplier.error ? <ErrorState error={selectedSupplier.error as Error} retry={()=>void selectedSupplier.refetch()}/> : selectedSupplier.data ? <SupplierReviewSummary data={selectedSupplier.data}/> : null}</section> : null}<section><h2 className="mb-3 text-lg font-semibold">{t('completedOrders')}</h2>{eligible.length ? <div className="grid gap-4 md:grid-cols-2">{eligible.map((order) => <Card key={order.id}><CardHeader><CardTitle className="text-base">{order.supplier?.name}</CardTitle><CardDescription>{order.order_number} · {order.lines.map((line)=>line.crop).join(', ')}</CardDescription></CardHeader><CardContent><Button onClick={()=>setSelectedId(order.id)}>{order.reviews.length ? <Pencil/> : <Star/>}{order.reviews.length ? t('editFeedback') : t('rateSupplier')}</Button></CardContent></Card>)}</div> : <EmptyState icon={Star} title={t('noReviewOrders')} body={t('reviewAfterDelivery')} />}</section><section><h2 className="mb-3 text-lg font-semibold">{t('myReviews')}</h2>{mine.data?.items.length ? <div className="grid gap-4 md:grid-cols-2">{mine.data.items.map((review)=><ReviewCard key={review.review_id} review={review}/>)}</div> : <EmptyState icon={MessageSquareText} title={t('noReviews')} body={t('noReviewsHelp')} />}</section></div>}{selected ? <ReviewDialog key={selected.id} order={selected} close={()=>setSelectedId('')}/> : null}</>
  if (!supplierMemberships.length) return <EmptyState icon={Star} title={t('noReviews')} body={t('noReviewsHelp')} />
  return <><PageTitle title={t('ratingsReviews')} description={t('supplierReviewHelp')} /><div className="space-y-6">{ratingQueries.map((query,index) => query.isLoading ? <LoadingPage key={index}/> : query.error ? <ErrorState key={index} error={query.error as Error} retry={()=>void query.refetch()}/> : query.data ? <SupplierReviewSummary key={query.data.organization.id} data={query.data}/> : null)}</div></>
}
