import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Clock3, LocateFixed, MapPin, Navigation, Radio, Route, ShieldCheck, Square, Truck } from 'lucide-react'
import { toast } from 'sonner'

import { TrackingMap } from '@/components/TrackingMap'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { dateTime, EmptyState, ErrorState, LoadingPage, PageTitle } from '@/components/common'
import { api } from '@/lib/api'
import type { DispatchTracking, Order, Session, TrackingMode } from '@/lib/types'

export function BuyerTrackingPage() {
  const orders = useQuery({ queryKey: ['orders'], queryFn: () => api<{items:Order[]}>('/api/orders') })
  const trackable = useMemo(() => orders.data?.items.flatMap((order) => order.dispatches.filter((dispatch) => dispatch.tracking_assigned).map((dispatch) => ({ order, dispatch }))) || [], [orders.data])
  const [dispatchId, setDispatchId] = useState('')
  const effectiveDispatchId = dispatchId || trackable[0]?.dispatch.id || ''
  const tracking = useQuery({ queryKey: ['dispatch-tracking', effectiveDispatchId], queryFn: () => api<DispatchTracking>(`/api/dispatches/${effectiveDispatchId}/tracking`), enabled: Boolean(effectiveDispatchId), refetchInterval: 7000, refetchIntervalInBackground: false })
  return <>
    <PageTitle title="Live delivery tracking" description="Choose a dispatch to view its vehicle. Each supplier dispatch is tracked independently." />
    {orders.isLoading ? <LoadingPage /> : orders.error ? <ErrorState error={orders.error} retry={() => void orders.refetch()} /> : !trackable.length ? <EmptyState icon={Truck} title="No tracked dispatches" body="Tracking appears after a supplier creates a dispatch and assigns an AgriLink driver." /> : <div className="space-y-5">
      <Card><CardContent className="grid gap-4 p-4 sm:grid-cols-[1fr_auto] sm:items-end"><label className="space-y-2 text-sm font-medium">Dispatch<Select value={effectiveDispatchId} onValueChange={setDispatchId}><SelectTrigger className="h-12"><SelectValue /></SelectTrigger><SelectContent>{trackable.map(({order, dispatch}) => <SelectItem key={dispatch.id} value={dispatch.id}>{order.order_number} · {dispatch.reference} · {dispatch.driver_name}</SelectItem>)}</SelectContent></Select></label><Badge variant="outline" className="h-10 justify-center px-4">Refreshes every 7 seconds</Badge></CardContent></Card>
      {tracking.isLoading ? <LoadingPage /> : tracking.error ? <ErrorState error={tracking.error} retry={() => void tracking.refetch()} /> : tracking.data ? <TrackingPanel tracking={tracking.data} /> : null}
    </div>}
  </>
}

function HealthBadge({ tracking }: { tracking: DispatchTracking }) {
  const health = tracking.tracking_health
  const live = health === 'live'
  const stale = health === 'stale'
  return <Badge variant={live ? 'default' : stale ? 'destructive' : 'secondary'} className="gap-1.5"><span className={`size-2 rounded-full ${live ? 'animate-pulse bg-white' : 'bg-current'}`} />{health.replaceAll('_', ' ')}</Badge>
}

function TrackingPanel({ tracking }: { tracking: DispatchTracking }) {
  const latest = tracking.locations.at(-1)
  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,.65fr)]">
    <Card className="overflow-hidden"><CardHeader className="flex-row items-center justify-between border-b"><div><CardTitle>{tracking.dispatch.reference}</CardTitle><p className="mt-1 text-sm text-muted-foreground">{tracking.order.order_number} · {tracking.order.supplier_name}</p></div><HealthBadge tracking={tracking} /></CardHeader><CardContent className="p-0"><TrackingMap tracking={tracking} /></CardContent></Card>
    <div className="space-y-4">
      {tracking.dispatch.tracking_mode === 'simulated' ? <Alert className="border-amber-300 bg-amber-50"><AlertTriangle /><AlertTitle>Simulated tracking</AlertTitle><AlertDescription>Demo coordinates follow a sample straight path and are not a real vehicle.</AlertDescription></Alert> : <Alert><ShieldCheck /><AlertTitle>Real GPS tracking</AlertTitle><AlertDescription>The assigned driver explicitly started location sharing from their phone.</AlertDescription></Alert>}
      {tracking.tracking_health === 'stale' ? <Alert variant="destructive"><Radio /><AlertTitle>Tracking disconnected</AlertTitle><AlertDescription>No update has arrived for more than 20 seconds. The marker stays at the last recorded location.</AlertDescription></Alert> : null}
      <Card><CardContent className="space-y-4 p-5"><Info icon={Truck} label="Vehicle" value={tracking.dispatch.vehicle_registration} /><Info icon={Navigation} label="Driver" value={`${tracking.driver.name}${tracking.driver.phone ? ` · ${tracking.driver.phone}` : ''}`} /><Info icon={MapPin} label="Pickup" value={tracking.pickup.label} /><Info icon={LocateFixed} label="Destination" value={tracking.destination.label} /><Info icon={Clock3} label="Last update" value={latest ? dateTime(latest.received_at) : 'Waiting for first location'} />{latest ? <p className="rounded-xl bg-secondary p-3 text-xs text-muted-foreground">Recorded accuracy: ±{Math.round(latest.accuracy_m)} m · No traffic ETA is calculated.</p> : null}</CardContent></Card>
      <p className="px-1 text-xs text-muted-foreground">Arrival is a driver status only. The buyer must inspect the produce and record receipt separately.</p>
    </div>
  </div>
}

function Info({icon:Icon,label,value}:{icon:typeof Truck;label:string;value:string}) { return <div className="flex gap-3"><span className="rounded-xl bg-secondary p-2.5 text-primary"><Icon className="size-5" /></span><div className="min-w-0"><p className="text-xs text-muted-foreground">{label}</p><p className="break-words font-medium">{value}</p></div></div> }

export function DriverPage({ session }: { session: Session }) {
  const qc = useQueryClient()
  const assignments = useQuery({ queryKey: ['driver-dispatches'], queryFn: () => api<{items:DispatchTracking[]}>('/api/driver/dispatches'), refetchInterval: 7000, refetchIntervalInBackground: false })
  const [dispatchId, setDispatchId] = useState('')
  const [modeOverride, setModeOverride] = useState<TrackingMode>()
  const [collecting, setCollecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [gpsError, setGpsError] = useState('')
  const simulationStep = useRef(0)
  const active = assignments.data?.items.find((item) => item.dispatch.id === dispatchId) || assignments.data?.items[0]
  const mode = modeOverride ?? active?.dispatch.tracking_mode ?? 'real'

  const activeId = active?.dispatch.id
  const pickupLatitude = active?.pickup.latitude
  const pickupLongitude = active?.pickup.longitude
  const destinationLatitude = active?.destination.latitude
  const destinationLongitude = active?.destination.longitude
  const sendPoint = useCallback(async (latitude:number, longitude:number, accuracy_m:number) => {
    if (!activeId) return
    await api(`/api/dispatches/${activeId}/locations`, { method:'POST', body:JSON.stringify({ latitude, longitude, accuracy_m, captured_at:new Date().toISOString(), client_update_id:crypto.randomUUID() }) })
    await Promise.all([qc.invalidateQueries({queryKey:['driver-dispatches']}), qc.invalidateQueries({queryKey:['dispatch-tracking', activeId]})])
  }, [activeId, qc])

  useEffect(() => {
    if (!collecting || !activeId) return
    let cancelled = false
    const tick = () => {
      if (cancelled || document.visibilityState !== 'visible') return
      if (mode === 'simulated') {
        const start = pickupLatitude != null && pickupLongitude != null ? {latitude:pickupLatitude,longitude:pickupLongitude} : {latitude:16.43,longitude:80.568}
        const end = destinationLatitude != null && destinationLongitude != null ? {latitude:destinationLatitude,longitude:destinationLongitude} : {latitude:16.5062,longitude:80.648}
        const ratio = Math.min(0.95, simulationStep.current++ / 12)
        void sendPoint(Number(start.latitude) + (Number(end.latitude)-Number(start.latitude))*ratio, Number(start.longitude) + (Number(end.longitude)-Number(start.longitude))*ratio, 12).catch((error:Error) => { setGpsError(error.message); setCollecting(false) })
      } else navigator.geolocation.getCurrentPosition(
        (position) => void sendPoint(position.coords.latitude, position.coords.longitude, Math.max(1, position.coords.accuracy)).catch((error:Error) => { setGpsError(error.message); setCollecting(false) }),
        (error) => { setGpsError(error.message || 'Location permission or GPS is unavailable.'); setCollecting(false) },
        { enableHighAccuracy:true, maximumAge:3000, timeout:12000 },
      )
    }
    tick(); const timer = window.setInterval(tick, 7000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [collecting, activeId, mode, pickupLatitude, pickupLongitude, destinationLatitude, destinationLongitude, sendPoint])

  const start = async () => {
    if (!active) return
    setBusy(true); setGpsError('')
    try {
      if (mode === 'real') await new Promise<GeolocationPosition>((resolve,reject) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,timeout:12000}) : reject(new Error('This browser does not support GPS.')))
      await api(`/api/dispatches/${active.dispatch.id}/tracking/start`, {method:'POST',body:JSON.stringify({mode})})
      simulationStep.current=0; setCollecting(true); await qc.invalidateQueries({queryKey:['driver-dispatches']})
      toast.success(mode === 'real' ? 'Real GPS sharing started' : 'Simulated tracking started')
    } catch (error) { setGpsError(error instanceof Error ? error.message : 'Tracking could not start.') } finally { setBusy(false) }
  }
  const stop = async () => { if (!active) return; setCollecting(false); setBusy(true); try { await api(`/api/dispatches/${active.dispatch.id}/tracking/stop`,{method:'POST'}); await qc.invalidateQueries({queryKey:['driver-dispatches']}); toast.success('Location sharing stopped') } catch(error){ toast.error(error instanceof Error?error.message:'Could not stop sharing') } finally{setBusy(false)} }
  const arrive = async () => { if (!active) return; setCollecting(false); setBusy(true); try { await api(`/api/dispatches/${active.dispatch.id}/tracking/arrival`,{method:'POST'}); await qc.invalidateQueries({queryKey:['driver-dispatches']}); toast.success('Arrival recorded; buyer receipt is still pending') } catch(error){ toast.error(error instanceof Error?error.message:'Could not mark arrival') } finally{setBusy(false)} }

  return <>
    <PageTitle title="Driver deliveries" description={`Signed in as ${session.user.full_name}. GPS is collected only after you choose Start Delivery.`} />
    {assignments.isLoading ? <LoadingPage /> : assignments.error ? <ErrorState error={assignments.error} retry={() => void assignments.refetch()} /> : !assignments.data?.items.length ? <EmptyState icon={Truck} title="No assigned deliveries" body="Ask the supplier to assign your driver account to a dispatch." /> : active ? <div className="space-y-5">
      <Card><CardContent className="p-4"><label className="space-y-2 text-sm font-medium">Assigned dispatch<Select value={active.dispatch.id} onValueChange={(value)=>{setCollecting(false);setModeOverride(undefined);setDispatchId(value)}}><SelectTrigger className="h-12"><SelectValue /></SelectTrigger><SelectContent>{assignments.data.items.map(item=><SelectItem key={item.dispatch.id} value={item.dispatch.id}>{item.order.order_number} · {item.dispatch.reference}</SelectItem>)}</SelectContent></Select></label></CardContent></Card>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]"><Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle>{active.dispatch.reference}</CardTitle><p className="mt-1 text-sm text-muted-foreground">{active.pickup.label} → {active.destination.label}</p></div><HealthBadge tracking={active}/></div></CardHeader><CardContent><TrackingMap tracking={active}/></CardContent></Card>
      <div className="space-y-4"><Card><CardContent className="space-y-4 p-5"><p className="font-semibold">Tracking mode</p><div className="grid grid-cols-2 gap-2"><Button type="button" variant={mode==='real'?'default':'outline'} disabled={collecting||active.dispatch.sharing_status==='arrived'} onClick={()=>setModeOverride('real')}><LocateFixed/>Real GPS</Button><Button type="button" variant={mode==='simulated'?'default':'outline'} disabled={collecting||active.dispatch.sharing_status==='arrived'} onClick={()=>setModeOverride('simulated')}><Route/>Simulated</Button></div>{mode==='simulated'?<Alert className="border-amber-300 bg-amber-50"><AlertTriangle/><AlertTitle>Simulated tracking</AlertTitle><AlertDescription>For demonstration only. No phone location is read.</AlertDescription></Alert>:<p className="text-sm text-muted-foreground">Your browser will request location permission. Updates are sent every 7 seconds only while this page is visible.</p>}{gpsError?<Alert variant="destructive"><AlertTriangle/><AlertTitle>Tracking problem</AlertTitle><AlertDescription>{gpsError}</AlertDescription></Alert>:null}<div className="grid gap-2">{active.dispatch.sharing_status!=='arrived'?<Button className="h-12" disabled={busy||collecting} onClick={()=>void start()}><Navigation/>{collecting?'Sharing location…':'Start Delivery'}</Button>:null}{(collecting||active.dispatch.sharing_status==='sharing')?<Button className="h-12" variant="outline" disabled={busy} onClick={()=>void stop()}><Square/>Stop Sharing</Button>:null}{active.dispatch.sharing_status!=='arrived'?<Button className="h-12" variant="secondary" disabled={busy} onClick={()=>void arrive()}><MapPin/>Mark Arrival</Button>:null}</div></CardContent></Card><p className="text-xs text-muted-foreground">Closing or backgrounding the page can pause browser GPS. Arrival does not confirm produce receipt.</p></div></div>
    </div>:null}
  </>
}
