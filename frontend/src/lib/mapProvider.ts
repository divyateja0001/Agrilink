export type MapProvider = {
  name: string
  tileUrl: string
  attribution: string
  maxZoom: number
}

// The view depends only on this adapter. A production provider can replace these
// values without changing tracking, authorization, or location persistence.
export const mapProvider: MapProvider = {
  name: import.meta.env.VITE_MAP_PROVIDER_NAME || 'OpenStreetMap',
  tileUrl: import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  attribution: import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: Number(import.meta.env.VITE_MAP_MAX_ZOOM || 19),
}
