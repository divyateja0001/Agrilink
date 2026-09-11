import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { mapProvider } from '@/lib/mapProvider'
import type { DispatchTracking } from '@/lib/types'

const pin = (kind: 'pickup'|'destination'|'vehicle') => L.divIcon({
  className: `agrilink-map-pin agrilink-map-pin-${kind}`,
  html: kind === 'vehicle' ? '<span aria-hidden="true">🚚</span>' : `<span aria-hidden="true">${kind === 'pickup' ? 'P' : 'D'}</span>`,
  iconSize: kind === 'vehicle' ? [42, 42] : [32, 32],
  iconAnchor: kind === 'vehicle' ? [21, 21] : [16, 16],
})

export function TrackingMap({ tracking }: { tracking: DispatchTracking }) {
  const elementRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const staticLayerRef = useRef<L.LayerGroup | null>(null)
  const vehicleRef = useRef<L.Marker | null>(null)
  const fitKeyRef = useRef('')

  useEffect(() => {
    if (!elementRef.current || mapRef.current) return
    const map = L.map(elementRef.current, { zoomControl: true, attributionControl: true }).setView([16.45, 80.6], 10)
    L.tileLayer(mapProvider.tileUrl, { attribution: mapProvider.attribution, maxZoom: mapProvider.maxZoom }).addTo(map)
    staticLayerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    const timer = window.setTimeout(() => map.invalidateSize(), 0)
    return () => { window.clearTimeout(timer); map.remove(); mapRef.current = null; staticLayerRef.current = null; vehicleRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = staticLayerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const pickup = tracking.pickup.latitude != null && tracking.pickup.longitude != null ? L.latLng(tracking.pickup.latitude, tracking.pickup.longitude) : undefined
    const destination = tracking.destination.latitude != null && tracking.destination.longitude != null ? L.latLng(tracking.destination.latitude, tracking.destination.longitude) : undefined
    if (pickup) L.marker(pickup, { icon: pin('pickup'), title: `Pickup: ${tracking.pickup.label}` }).bindTooltip(`Pickup · ${tracking.pickup.label}`).addTo(layer)
    if (destination) L.marker(destination, { icon: pin('destination'), title: `Destination: ${tracking.destination.label}` }).bindTooltip(`Destination · ${tracking.destination.label}`).addTo(layer)
    const path = tracking.locations.map((item) => L.latLng(item.latitude, item.longitude))
    if (path.length > 1) L.polyline(path, { color: '#176B43', weight: 4, opacity: .75 }).addTo(layer)
    const latest = path.at(-1)
    if (latest) {
      if (vehicleRef.current) vehicleRef.current.setLatLng(latest)
      else vehicleRef.current = L.marker(latest, { icon: pin('vehicle'), title: `${tracking.dispatch.vehicle_registration} current recorded position`, zIndexOffset: 1000 }).addTo(map)
    } else if (vehicleRef.current) {
      vehicleRef.current.remove(); vehicleRef.current = null
    }
    const fitKey = `${tracking.dispatch.id}:${pickup?.toString()}:${destination?.toString()}`
    if (fitKeyRef.current !== fitKey) {
      const bounds = L.latLngBounds([pickup, destination, latest].filter(Boolean) as L.LatLng[])
      if (bounds.isValid()) map.fitBounds(bounds.pad(.18), { maxZoom: 14 })
      fitKeyRef.current = fitKey
    }
  }, [tracking])

  return <div ref={elementRef} className="h-[320px] w-full overflow-hidden rounded-2xl border bg-secondary sm:h-[440px]" role="img" aria-label="Dispatch map showing pickup, destination, and the latest recorded vehicle position" />
}
