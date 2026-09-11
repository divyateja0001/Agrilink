import { cloneElement, isValidElement, useId } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { AlertTriangle, Boxes } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import i18n from '@/i18n'
import { interfaceLocale, translateInterfaceText } from '@/interfaceTranslations'

export const inr = (paise = 0) => new Intl.NumberFormat(interfaceLocale(i18n.language), { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(paise / 100)
export const shortDate = (value: string) => new Intl.DateTimeFormat(interfaceLocale(i18n.language), { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
export const dateTime = (value: string) => new Intl.DateTimeFormat(interfaceLocale(i18n.language), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
export const daysFromNow = (days: number) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10)

export function LoadingPage() { return <div className="grid gap-4" aria-label={translateInterfaceText('Loading', i18n.language)}><Skeleton className="h-10 w-52" /><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[1,2,3,4].map(x => <Skeleton key={x} className="h-32 rounded-xl" />)}</div><Skeleton className="h-72 rounded-xl" /></div> }
export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) { return <Alert variant="destructive"><AlertTriangle /><AlertTitle>{translateInterfaceText('Something needs attention', i18n.language)}</AlertTitle><AlertDescription className="flex flex-wrap items-center gap-3"><span>{translateInterfaceText(error.message, i18n.language)}</span>{retry && <Button size="sm" variant="outline" onClick={retry}>{translateInterfaceText('Try again', i18n.language)}</Button>}</AlertDescription></Alert> }
export function EmptyState({ icon: Icon = Boxes, title, body, action }: { icon?: typeof Boxes; title: string; body: string; action?: ReactNode }) { return <Card className="border-dashed"><CardContent className="flex min-h-52 flex-col items-center justify-center gap-3 text-center"><span className="rounded-full bg-secondary p-3"><Icon className="size-6 text-primary" /></span><div><h3 className="font-semibold">{title}</h3><p className="mt-1 max-w-md text-sm text-muted-foreground">{body}</p></div>{action}</CardContent></Card> }
export function StatusBadge({ status }: { status: string }) {
  const positive = ['active', 'accepted', 'agreed', 'confirmed', 'received', 'paid', 'completed', 'resolved'].includes(status)
  const warning = ['awaiting_buyer', 'awaiting_supplier', 'partially_fulfilled', 'partially_dispatched', 'partially_received', 'partially_paid', 'under_review'].includes(status)
  const danger = ['cancelled', 'rejected', 'withdrawn', 'failure'].includes(status)
  return <Badge variant={positive ? 'default' : warning ? 'secondary' : danger ? 'destructive' : 'outline'} className="whitespace-nowrap capitalize">{translateInterfaceText(status.replaceAll('_', ' '), i18n.language)}</Badge>
}
export function PageTitle({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) { return <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1><p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p></div>{actions&&<div className="flex flex-wrap gap-2">{actions}</div>}</div> }
export function Field({label,children,className=''}:{label:string;children:ReactNode;className?:string}){
  const id = useId()
  const element = children as ReactElement<Record<string, unknown>>
  const control = isValidElement(element) ? cloneElement(element, { id, 'aria-label': element.props['aria-label'] ?? label }) : children
  return <div className={`min-w-0 space-y-2 ${className}`}><Label htmlFor={id}>{label}</Label>{control}</div>
}
