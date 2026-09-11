import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, CheckCheck, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { dateTime, EmptyState, ErrorState, LoadingPage, PageTitle } from '@/components/common'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { api } from '@/lib/api'

type Notice = { id: string; title: string; body: string; link?: string; read: boolean; created_at: string }
type PushConfig = { enabled: boolean; public_key: string; subscribed: boolean; subscriptions: {id:string}[] }

function applicationServerKey(value: string) {
  const padding = '='.repeat((4 - value.length % 4) % 4)
  const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map((character) => character.charCodeAt(0)))
}

export function NotificationsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const notices = useQuery({ queryKey:['notifications'], queryFn:()=>api<{items:Notice[];unread:number}>('/api/notifications') })
  const push = useQuery({ queryKey:['push-config'], queryFn:()=>api<PushConfig>('/api/push/config') })
  const read = useMutation({ mutationFn:(id:string)=>api(`/api/notifications/${id}/read`,{method:'POST'}), onSuccess:()=>qc.invalidateQueries({queryKey:['notifications']}) })
  const readAll = useMutation({ mutationFn:()=>api('/api/notifications/read-all',{method:'POST'}), onSuccess:()=>qc.invalidateQueries({queryKey:['notifications']}) })
  const enable = useMutation({
    mutationFn: async () => {
      if (!push.data?.enabled) throw new Error('Browser push is not configured on the server.')
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('This browser does not support push notifications.')
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') throw new Error('Notification permission was not granted. You can still use in-app alerts.')
      const registration = await navigator.serviceWorker.register('/push-sw.js')
      const existing = await registration.pushManager.getSubscription()
      const subscription = existing ?? await registration.pushManager.subscribe({ userVisibleOnly:true, applicationServerKey:applicationServerKey(push.data.public_key) })
      return api('/api/push/subscriptions',{method:'POST',body:JSON.stringify(subscription.toJSON())})
    },
    onSuccess: async()=>{toast.success(t('browserAlertsEnabled'));await qc.invalidateQueries({queryKey:['push-config']})},
    onError:(error:Error)=>toast.error(error.message),
  })
  const disable = useMutation({ mutationFn:async()=>{if(!push.data?.subscriptions[0])return;await api(`/api/push/subscriptions/${push.data.subscriptions[0].id}`,{method:'DELETE'});const registration=await navigator.serviceWorker?.getRegistration('/');const subscription=await registration?.pushManager.getSubscription();await subscription?.unsubscribe()},onSuccess:async()=>{toast.success(t('browserAlertsDisabled'));await qc.invalidateQueries({queryKey:['push-config']})},onError:(error:Error)=>toast.error(error.message) })
  return <><PageTitle title={t('notifications')} description={t('notificationsHelp')} actions={notices.data?.unread ? <Button variant="outline" onClick={()=>readAll.mutate()} disabled={readAll.isPending}><CheckCheck/>{t('markAllRead')}</Button> : undefined}/><Alert className="mb-5"><Bell/><AlertTitle>{t('browserAlerts')}</AlertTitle><AlertDescription className="mt-2 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between"><span>{push.isLoading ? t('checkingBrowserAlerts') : !push.data?.enabled ? t('pushNotConfigured') : push.data.subscribed ? t('pushActive') : t('enablePushHelp')}</span>{push.data?.enabled ? push.data.subscribed ? <Button variant="outline" onClick={()=>disable.mutate()} disabled={disable.isPending}><BellOff/>{t('disable')}</Button> : <Button onClick={()=>enable.mutate()} disabled={enable.isPending}>{enable.isPending?<Loader2 className="animate-spin"/>:<Bell/>}{t('enableBrowserAlerts')}</Button> : null}</AlertDescription></Alert>{notices.isLoading?<LoadingPage/>:notices.error?<ErrorState error={notices.error} retry={()=>void notices.refetch()}/>:notices.data?.items.length?<div className="space-y-3">{notices.data.items.map((item)=><Card key={item.id} className={!item.read?'border-primary/40':''}><CardContent className="flex gap-4 p-4"><span className="h-fit rounded-full bg-secondary p-2 text-primary"><Bell className="size-4"/></span><div className="min-w-0 flex-1"><a href={item.link||'/notifications'} className="font-semibold hover:underline">{item.title}</a><p className="text-sm text-muted-foreground">{item.body}</p><small>{dateTime(item.created_at)}</small></div>{!item.read&&<Button size="sm" variant="outline" onClick={()=>read.mutate(item.id)}>{t('markRead')}</Button>}</CardContent></Card>)}</div>:<EmptyState icon={Bell} title={t('allCaughtUp')} body={t('notificationEmpty')}/>}</>
}
