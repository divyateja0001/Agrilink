import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Camera, Loader2, MapPin, RotateCcw, Search, Sprout, Star, Truck, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, ErrorState, Field, LoadingPage, PageTitle, daysFromNow, shortDate } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import type { DeliveryMode, Lot, ProcurementDraft, Session } from '@/lib/types'

export function ProducePage({ session }: { session: Session }) {
  const farmer = session.roles.includes('farmer')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Lot>()
  const [captureLot, setCaptureLot] = useState<Lot>()
  const produce = useQuery({ queryKey: ['produce', farmer], queryFn: () => api<{ items: Lot[] }>(`/api/produce${farmer ? '?mine=true' : ''}`) })
  const create = useMutation({
    mutationFn: (body: object) => api<Lot>('/api/produce', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (lot) => { setOpen(false); setCaptureLot(lot); void queryClient.invalidateQueries({ queryKey: ['produce'] }); toast.success('Draft saved. Capture a photo to publish it.') },
    onError: (error: Error) => toast.error(error.message),
  })
  const archive = useMutation({
    mutationFn: ({ lot, operation }: { lot: Lot; operation: 'archive' | 'restore' }) => api<Lot>(`/api/produce/${lot.id}/${operation}`, { method: 'POST', body: JSON.stringify({ version: lot.version }) }),
    onSuccess: (lot) => { toast.success(lot.status === 'archived' ? 'Listing archived' : 'Listing restored'); setSelected(undefined); void queryClient.invalidateQueries({ queryKey: ['produce'] }) },
    onError: (error: Error) => toast.error(error.message),
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    create.mutate({
      crop: form.get('crop'), variety: form.get('variety'), quality_grade: form.get('quality'), quantity_kg: form.get('quantity'),
      asking_price_inr: form.get('price'), location: form.get('location'), harvest_date: form.get('harvest'),
      available_from: form.get('from'), available_until: form.get('until'), description: form.get('description'),
      delivery_mode: form.get('delivery_mode'), delivery_service_location: form.get('delivery_service_location'),
      delivery_radius_km: form.get('delivery_radius_km'), delivery_charge_inr: form.get('delivery_charge_inr'),
    })
  }
  const startProcurement = (lot: Lot) => {
    const draft: ProcurementDraft = { crop: lot.crop, variety: lot.variety, acceptable_quality: lot.quality_grade, quantity_kg: Math.min(lot.available_quantity_kg, 1000), destination: '', delivery_deadline: daysFromNow(14), budget_price_inr: lot.asking_price_inr, delivery_mode: lot.delivery_mode }
    localStorage.setItem('agrilink-requirement-draft', JSON.stringify(draft)); navigate('/requirements')
  }
  const items = produce.data?.items.filter((lot) => `${lot.crop} ${lot.variety} ${lot.location}`.toLowerCase().includes(search.toLowerCase())) ?? []

  return <>
    <PageTitle title={farmer ? 'My produce' : 'Supplier discovery'} description={farmer ? 'Publish fresh stock, choose delivery options, and manage active listings.' : 'Open a listing to review supply and start a procurement requirement.'} actions={farmer ? <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button><Sprout />Add produce</Button></DialogTrigger><DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>Add produce</DialogTitle><DialogDescription>Save the details, then take a location-recorded photo with this website to publish.</DialogDescription></DialogHeader><ProduceForm submit={submit} pending={create.isPending} /></DialogContent></Dialog> : undefined} />
    <div className="relative mb-5 max-w-md"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input className="pl-9" placeholder="Search crop, variety, or location" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
    {produce.isLoading ? <LoadingPage /> : produce.error ? <ErrorState error={produce.error} retry={() => void produce.refetch()} /> : !items.length ? <EmptyState icon={Sprout} title="No produce found" body={farmer ? 'Add produce or change your search.' : 'No active supplier listings match your search.'} /> : (
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((lot) => <Card key={lot.id} className="relative overflow-hidden">
          {farmer && lot.status !== 'archived' ? <Button type="button" size="icon" variant="destructive" className="absolute right-3 top-3 z-10 size-9 rounded-full" aria-label={`Archive ${lot.crop}`} onClick={() => window.confirm('Archive this listing? Existing orders and reservations will be preserved.') && archive.mutate({ lot, operation: 'archive' })}><X /></Button> : null}
          <button type="button" className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => setSelected(lot)} aria-label={`Open ${lot.crop} listing`}>
            <div className="relative"><img src={lot.photo_url || '/produce/tomatoes.png'} alt={`${lot.crop} ${lot.variety}`} className="h-44 w-full object-cover" /><Badge className="absolute left-3 top-3 bg-white text-foreground">Grade {lot.quality_grade}</Badge>{farmer ? <Badge variant="secondary" className={`absolute top-3 capitalize ${lot.status === 'archived' ? 'right-3' : 'right-14'}`}>{lot.status}</Badge> : null}</div>
            <CardHeader className="pb-3"><div className="flex justify-between gap-3"><div><CardTitle>{lot.crop}</CardTitle><CardDescription>{lot.variety}</CardDescription>{lot.supplier ? <div className="mt-2 flex flex-wrap items-center gap-2 text-xs"><span className="font-medium text-foreground">{lot.supplier.name}</span>{lot.supplier.rating_summary?.review_count ? <span className="flex items-center gap-1 text-[#8a5b00]"><Star className="size-3.5 fill-[#F2B84B]" />{lot.supplier.rating_summary.average_rating} · {lot.supplier.rating_summary.review_count} reviews</span> : <span className="text-muted-foreground">No reviews yet</span>}</div> : null}</div><b className="text-primary">₹{lot.asking_price_inr}/kg</b></div></CardHeader>
            <CardContent><div className="grid grid-cols-2 gap-3 rounded-xl bg-muted p-3 text-sm"><div><small className="block text-muted-foreground">Available</small><b>{lot.available_quantity_kg} kg</b></div><div><small className="block text-muted-foreground">On hand</small><b>{lot.quantity_on_hand_kg} kg</b></div></div><div className="mt-4 space-y-1 text-sm text-muted-foreground"><p className="flex items-center gap-2"><Truck className="size-4" />{deliveryLabel(lot.delivery_mode)}</p><p className="flex items-center gap-2"><MapPin className="size-4" />{lot.location}{lot.location_recorded ? ' · Location recorded' : ''}</p><p>{shortDate(lot.available_from)} – {shortDate(lot.available_until)}</p></div></CardContent>
          </button>
        </Card>)}
      </div>
    )}

    <Dialog open={!!selected} onOpenChange={(value) => !value && setSelected(undefined)}><DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg"><DialogHeader><DialogTitle>{selected?.crop} · {selected?.variety}</DialogTitle><DialogDescription>{selected?.description || 'Fresh produce listing'}</DialogDescription></DialogHeader>{selected ? <div className="space-y-4"><img className="h-56 w-full rounded-xl object-cover" src={selected.photo_url || '/produce/tomatoes.png'} alt={`${selected.crop} ${selected.variety}`} /><div className="rounded-xl border p-4 text-sm"><p><b>{selected.available_quantity_kg} kg</b> available at <b>₹{selected.asking_price_inr}/kg</b></p><p className="mt-2"><b>Delivery:</b> {deliveryLabel(selected.delivery_mode)}</p>{selected.delivery_mode === 'seller_delivery' ? <p>{selected.delivery_service_location} · within {selected.delivery_radius_km} km · ₹{selected.delivery_charge_inr ?? 0} per order</p> : null}<p className="mt-2 text-muted-foreground">{selected.location}{selected.location_recorded ? ' · Device location recorded' : ''}</p></div>{farmer ? <div className="flex flex-wrap gap-2">{selected.status === 'archived' ? <Button onClick={() => archive.mutate({ lot: selected, operation: 'restore' })}><RotateCcw />Restore listing</Button> : <Button variant="destructive" onClick={() => window.confirm('Archive this listing? Existing orders and reservations will be preserved.') && archive.mutate({ lot: selected, operation: 'archive' })}><Archive />Archive listing</Button>}{!selected.photo_url ? <Button variant="outline" onClick={() => { setSelected(undefined); setCaptureLot(selected) }}><Camera />Capture photo</Button> : null}</div> : <Button className="w-full" onClick={() => startProcurement(selected)}>Create requirement from this listing</Button>}</div> : null}</DialogContent></Dialog>
    <Dialog open={!!captureLot} onOpenChange={(value) => !value && setCaptureLot(undefined)}><DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl"><DialogHeader><DialogTitle>Capture produce photo</DialogTitle><DialogDescription>This website records the device location and time. It is not an independent location certification.</DialogDescription></DialogHeader>{captureLot ? <CameraCapture lot={captureLot} done={() => { setCaptureLot(undefined); void queryClient.invalidateQueries({ queryKey: ['produce'] }) }} /> : null}</DialogContent></Dialog>
  </>
}

function ProduceForm({ submit, pending }: { submit: (event: FormEvent<HTMLFormElement>) => void; pending: boolean }) {
  const [mode, setMode] = useState<DeliveryMode>('buyer_pickup')
  return <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2"><Field label="Crop"><Input name="crop" defaultValue="Tomato" required /></Field><Field label="Variety"><Input name="variety" defaultValue="Arka Rakshak" required /></Field><Field label="Quality"><Select name="quality" defaultValue="A"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{['A', 'B', 'C'].map((grade) => <SelectItem key={grade} value={grade}>Grade {grade}</SelectItem>)}</SelectContent></Select></Field><Field label="Quantity (kg)"><Input name="quantity" type="number" min=".001" step=".001" required /></Field><Field label="Price (₹/kg)"><Input name="price" type="number" min=".01" step=".01" required /></Field><Field label="Produce location"><Input name="location" defaultValue="Guntur, Andhra Pradesh" required /></Field><Field label="Harvest date"><Input name="harvest" type="date" defaultValue={daysFromNow(0)} required /></Field><Field label="Available from"><Input name="from" type="date" defaultValue={daysFromNow(0)} required /></Field><Field label="Available until"><Input name="until" type="date" defaultValue={daysFromNow(14)} required /></Field><Field label="Delivery mode"><Select name="delivery_mode" value={mode} onValueChange={(value) => setMode(value as DeliveryMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="buyer_pickup">Buyer Pickup</SelectItem><SelectItem value="seller_delivery">Delivery Available</SelectItem></SelectContent></Select></Field>{mode === 'seller_delivery' ? <><Field label="Delivery service location"><Input name="delivery_service_location" defaultValue="Guntur, Andhra Pradesh" required /></Field><Field label="Delivery radius (km)"><Input name="delivery_radius_km" type="number" min="1" step="0.1" defaultValue="50" required /></Field><Field label="Delivery charge (₹/order)"><Input name="delivery_charge_inr" type="number" min="0" step="0.01" defaultValue="0" /></Field></> : null}<Field label="Description" className="sm:col-span-2"><Textarea name="description" /></Field><Button className="sm:col-span-2" disabled={pending}>{pending ? <Loader2 className="animate-spin" /> : null}Save draft and capture photo</Button></form>
}

function CameraCapture({ lot, done }: { lot: Lot; done: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const upload = useMutation({
    mutationFn: async () => {
      const video = videoRef.current
      if (!video) throw new Error('Camera preview is not ready.')
      const position = await new Promise<GeolocationPosition>((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }))
      const canvas = document.createElement('canvas'); canvas.width = video.videoWidth; canvas.height = video.videoHeight
      canvas.getContext('2d')?.drawImage(video, 0, 0)
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error('Could not capture the photo.')), 'image/jpeg', 0.9))
      const capture = await api<{ capture_token: string }>(`/api/produce/${lot.id}/photo-capture-session`, { method: 'POST', body: JSON.stringify({}) })
      const form = new FormData(); form.set('photo', blob, 'camera.jpg'); form.set('capture_token', capture.capture_token); form.set('latitude', String(position.coords.latitude)); form.set('longitude', String(position.coords.longitude)); form.set('accuracy_m', String(position.coords.accuracy)); form.set('captured_at', new Date(position.timestamp).toISOString())
      return api(`/api/produce/${lot.id}/photo`, { method: 'POST', body: form })
    },
    onSuccess: () => { toast.success('Photo and location recorded. Listing published.'); done() },
    onError: (failure: Error) => setError(failure.message),
  })
  useEffect(() => {
    let active = true
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false }).then((stream) => { if (!active) { stream.getTracks().forEach((track) => track.stop()); return }; streamRef.current = stream; if (videoRef.current) { videoRef.current.srcObject = stream; void videoRef.current.play(); setReady(true) } }).catch(() => setError('Camera permission is required. Allow camera access in this browser and try again.'))
    return () => { active = false; streamRef.current?.getTracks().forEach((track) => track.stop()) }
  }, [])
  return <div className="space-y-4"><div className="overflow-hidden rounded-xl bg-black"><video ref={videoRef} playsInline muted className="aspect-video w-full object-cover" /></div>{error ? <p role="alert" className="text-sm text-destructive">{error}</p> : <p className="text-sm text-muted-foreground">Capturing also requests your current location. Accuracy must be within 500 metres.</p>}<Button className="w-full" disabled={!ready || upload.isPending} onClick={() => { setError(''); upload.mutate() }}>{upload.isPending ? <Loader2 className="animate-spin" /> : <Camera />}Capture photo and publish</Button></div>
}

const deliveryLabel = (mode: DeliveryMode) => mode === 'seller_delivery' ? 'Delivery Available' : 'Buyer Pickup'
