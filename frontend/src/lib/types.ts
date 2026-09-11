export type Role = 'farmer' | 'buyer' | 'fpo_manager' | 'admin' | 'driver'
export type DeliveryMode = 'buyer_pickup' | 'seller_delivery'
export type RatingSummary = { average_rating: number; quality_rating: number; delivery_rating: number; communication_rating: number; review_count: number }
export type Organization = { id: string; name: string; type: string; location: string; verified: boolean; is_active: boolean; rating_summary?: RatingSummary }
export type Session = {
  authenticated: true
  user: { id: string; email: string; full_name: string; phone?: string; locale: string; is_active: boolean }
  memberships: { id: string; role: Role; organization: Organization }[]
  roles: Role[]
  csrf_token: string
}
export type SessionResponse = Session | { authenticated: false }
export type Lot = {
  id: string; farmer_organization_id: string; crop: string; variety: string; quality_grade: string
  quantity_on_hand_kg: number; available_quantity_kg: number; asking_price_paise: number; asking_price_inr: number
  location: string; harvest_date: string; available_from: string; available_until: string; description: string
  photo_url?: string; location_recorded: boolean; status: string; version: number; delivery_mode: DeliveryMode
  delivery_service_location?: string; delivery_radius_km?: number; delivery_charge_paise?: number; delivery_charge_inr?: number
  supplier?: Organization
}
export type Requirement = {
  id: string; buyer_organization_id: string; crop: string; variety?: string; quantity_kg: number
  acceptable_quality: string; destination: string; delivery_deadline: string; budget_price_paise?: number
  budget_price_inr?: number; notes: string; status: string; version: number; delivery_mode: DeliveryMode
}
export type Quote = {
  id: string; status: string; version: number; side: 'buyer' | 'supplier' | 'admin'; requirement: Requirement; supplier: Organization
  revision: QuoteRevision
  actions: NegotiationActions
}
export type QuoteAllocation = { id: string; quantity_kg: number; lot: Lot; farmer: Organization }
export type QuoteRevision = {
  id: string; number: number; action: string; quantity_kg: number; price_paise_per_kg: number
  price_inr_per_kg: number; total_paise: number; quality_grade: string; delivery_date: string
  delivery_terms: string; delivery_mode: DeliveryMode; delivery_charge_paise: number; delivery_charge_inr: number; note: string; created_at: string; allocations: QuoteAllocation[]
  actor: { id: string; name: string }; actor_organization?: Organization
}
export type NegotiationActions = {
  can_counter: boolean; can_accept_terms: boolean; can_confirm_order: boolean
  can_reject: boolean; can_withdraw: boolean; can_message: boolean
}
export type NegotiationMessage = {
  id: string; body: string; created_at: string; mine: boolean
  author: { id: string; name: string }; organization: Organization
}
export type NegotiationDetail = Quote & { revisions: QuoteRevision[]; messages: NegotiationMessage[] }
export type ProcurementDraft = {
  crop?: string; variety?: string; quantity_kg?: number; acceptable_quality?: string
  destination?: string; delivery_deadline?: string; budget_price_inr?: number
  price_inr_per_kg?: number; delivery_terms?: string; notes?: string; delivery_mode?: DeliveryMode
}
export type ProcurementAdvice = {
  answer: string; suggestions: string[]; warnings: string[]; draft?: ProcurementDraft; source?: 'mistral' | 'rule_based'; degraded_reason?: string
  source_record_ids: string[]; request_id: string; model: string; generated_at: string; advisory: true
}
export type OrderLine = { id: string; crop: string; variety: string; quality_grade: string; agreed_quantity_kg: number; agreed_price_paise_per_kg: number; total_paise: number; delivery_terms: string; reserved_remaining_kg: number; dispatched_kg: number; received_kg: number; outstanding_kg: number }
export type TrackingEvent = { id: string; status: string; note: string; created_at: string }
export type Review = { review_id: string; order_id: string; order_number: string; supplier_id: string; supplier_name: string; reviewed_role: 'supplier'|'fpo'; overall_rating: number; quality_rating: number; delivery_rating: number; communication_rating: number; comment: string; version: number; buyer_label: string; created_at: string; updated_at: string; order: { crops: string[]; quantity_kg: number; delivery_deadline?: string } }
export type OrderParty = { id: string; name: string; type: string }
export type OrderDispatch = { id:string; reference:string; status:string; carrier_name?:string; carrier_phone?:string; note:string; created_at:string; tracking_assigned:boolean; sharing_status?:TrackingSharingStatus; tracking_mode?:TrackingMode; vehicle_registration?:string; driver_name?:string }
export type Order = { id: string; order_number: string; order_group_id: string; requirement_id: string; buyer_organization_id: string; supplier_organization_id: string; coordinating_fpo_id?: string; supplier?: OrderParty; coordinating_fpo?: OrderParty; status: string; payment_status: string; delivery_deadline: string; delivery_mode: DeliveryMode; delivery_charge_paise: number; version: number; lines: OrderLine[]; total_paise: number; payable_paise: number; review_eligible: boolean; reviews: Review[]; tracking_events: TrackingEvent[]; dispatches: OrderDispatch[]; comments?: { id: string; body: string; created_at: string }[]; payment_events?: { id: string; amount_paise: number; outcome: string; reference: string; simulated: boolean }[] }

export type TrackingMode = 'real' | 'simulated'
export type TrackingSharingStatus = 'not_started' | 'sharing' | 'stopped' | 'arrived'
export type TrackingPoint = { id:string; latitude:number; longitude:number; accuracy_m:number; captured_at:string; received_at:string; simulated:boolean }
export type DispatchTracking = {
  dispatch: { id:string; reference:string; status:string; carrier_name?:string; carrier_phone?:string; vehicle_registration:string; tracking_mode:TrackingMode; sharing_status:TrackingSharingStatus; started_at?:string; stopped_at?:string; arrived_at?:string; last_location_at?:string; version:number }
  order: { id:string; order_number:string; status:string; supplier_name:string; buyer_name:string }
  driver: { id:string; name:string; phone?:string }
  pickup: { label:string; latitude?:number; longitude?:number }
  destination: { label:string; latitude?:number; longitude?:number }
  locations: TrackingPoint[]
  tracking_health: 'live'|'waiting'|'stale'|TrackingSharingStatus
  server_time:string
  notice:string
}

export type AssistantConversation = { id: string; title: string; role: 'buyer'|'farmer'|'fpo_manager'; language: 'en'|'te'|'hi'|'ta'; created_at: string; updated_at: string }
export type AssistantMessage = { id: string; role: 'user'|'assistant'; content: string; source: string; model?: string; status: string; metadata: Record<string, unknown>; created_at: string }
