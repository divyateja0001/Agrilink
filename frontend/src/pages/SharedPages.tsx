import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { dateTime, EmptyState, ErrorState, Field, LoadingPage, PageTitle, StatusBadge } from '@/components/common'
import { api } from '@/lib/api'
import type { Lot, Session } from '@/lib/types'

type Participant = {
  id: string
  email: string
  full_name: string
  is_active: boolean
  memberships: { role: string }[]
}

export function MembersPage({session}:{session:Session}){const q=useQuery({queryKey:['fpo-supply'],queryFn:()=>api<{items:Lot[]}>('/api/produce')});if(!session.roles.includes('fpo_manager'))return <Navigate to="/"/>;return <><PageTitle title="Authorized member supply" description="Combined available supply across explicitly authorized member farms."/><Alert className="mb-5"><ShieldCheck/><AlertTitle>Scoped access</AlertTitle><AlertDescription>Backend authorization prevents access to unrelated farmers. Allocation previews never reserve stock.</AlertDescription></Alert>{q.isLoading?<LoadingPage/>:<div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{q.data?.items.map(x=><Card key={x.id}><CardContent className="p-5"><div className="flex justify-between"><div><b>{x.crop}</b><p className="text-sm text-muted-foreground">{x.location}</p></div><Badge variant="secondary">Grade {x.quality_grade}</Badge></div><p className="mt-5 text-2xl font-semibold">{x.available_quantity_kg} kg</p><small className="text-muted-foreground">Available member supply</small></CardContent></Card>)}</div>}</>}

export function AdminPage({ session }: { session: Session }) {
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['participants'], queryFn: () => api<{ items: Participant[] }>('/api/admin/participants') })
  const disputes = useQuery({ queryKey: ['disputes'], queryFn: () => api<{ items: any[] }>('/api/admin/disputes') })
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => api<{ items: any[] }>('/api/admin/audit') })
  const suspension = useMutation({
    mutationFn: ({ id, suspended }: { id: string; suspended: boolean }) => api(`/api/admin/users/${id}/suspension`, { method: 'POST', body: JSON.stringify({ suspended }) }),
    onSuccess: async (_, variables) => {
      toast.success(variables.suspended ? 'Account suspended' : 'Account restored')
      await queryClient.invalidateQueries({ queryKey: ['participants'] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  if (!session.roles.includes('admin')) return <Navigate to="/" />
  return <>
    <PageTitle title="Marketplace administration" description="Participant controls, dispute review and audit evidence." />
    <div className="grid gap-6 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>Participants</CardTitle><CardDescription>Public registration cannot grant elevated roles. Suspended accounts cannot sign in.</CardDescription></CardHeader><CardContent className="space-y-3">
        {users.isLoading ? <LoadingPage /> : users.error ? <ErrorState error={users.error} retry={() => void users.refetch()} /> : users.data?.items.map((participant) => <div key={participant.id} className="flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><b className="truncate">{participant.full_name}</b><Badge variant={participant.is_active ? 'secondary' : 'destructive'}>{participant.is_active ? 'Active' : 'Suspended'}</Badge></div><small className="block truncate text-muted-foreground">{participant.email} · {participant.memberships.map((membership) => membership.role.replace('_', ' ')).join(', ')}</small></div>
          <AlertDialog><AlertDialogTrigger asChild><Button size="sm" variant={participant.is_active ? 'outline' : 'default'} disabled={participant.id === session.user.id || suspension.isPending}>{participant.is_active ? 'Suspend' : 'Restore'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{participant.is_active ? 'Suspend account?' : 'Restore account?'}</AlertDialogTitle><AlertDialogDescription>{participant.is_active ? `${participant.full_name} will be signed out immediately and cannot sign in until restored.` : `${participant.full_name} will be able to sign in again with their existing password.`}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction variant={participant.is_active ? 'destructive' : 'default'} onClick={() => suspension.mutate({ id: participant.id, suspended: participant.is_active })}>{participant.is_active ? 'Suspend account' : 'Restore account'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
        </div>)}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Disputes</CardTitle></CardHeader><CardContent>{disputes.data?.items.length ? disputes.data.items.map((item) => <div key={item.id} className="mb-3 rounded-xl border p-3"><div className="flex justify-between"><b>Order issue</b><StatusBadge status={item.status} /></div><p className="mt-2 text-sm text-muted-foreground">{item.reason}</p></div>) : <EmptyState title="No disputes" body="Submitted order issues appear here." />}</CardContent></Card>
    </div>
    <Card className="mt-6"><CardHeader><CardTitle>Audit history</CardTitle></CardHeader><CardContent>{audit.data?.items.slice(0, 20).map((item) => <div key={item.id} className="grid gap-1 border-b py-3 text-sm sm:grid-cols-[220px_1fr_180px]"><b>{item.action}</b><span className="text-muted-foreground">{item.entity_type} {item.entity_id?.slice(0, 8)}</span><time>{dateTime(item.created_at)}</time></div>)}</CardContent></Card>
  </>
}

export function SettingsPage({session}:{session:Session}){const[name,setName]=useState(session.user.full_name),[phone,setPhone]=useState(session.user.phone||'');const save=useMutation({mutationFn:()=>api('/api/profile',{method:'PATCH',body:JSON.stringify({full_name:name,phone})}),onSuccess:()=>toast.success('Profile saved'),onError:(e:Error)=>toast.error(e.message)});return <><PageTitle title="Profile & organization" description="Personal details and recorded organization identity."/><div className="grid gap-6 lg:grid-cols-2"><Card><CardHeader><CardTitle>Profile</CardTitle></CardHeader><CardContent className="space-y-4"><Field label="Full name"><Input value={name} onChange={e=>setName(e.target.value)}/></Field><Field label="Email"><Input value={session.user.email} disabled/></Field><Field label="Phone"><Input value={phone} onChange={e=>setPhone(e.target.value)}/></Field><Button onClick={()=>save.mutate()}>Save profile</Button></CardContent></Card><Card><CardHeader><CardTitle>Organizations</CardTitle><CardDescription>Badges appear only for recorded verification.</CardDescription></CardHeader><CardContent className="space-y-3">{session.memberships.map(m=><div key={m.id} className="rounded-xl border p-4"><div className="flex justify-between"><div><b>{m.organization.name}</b><p className="text-sm text-muted-foreground">{m.organization.location} · {m.role.replace('_',' ')}</p></div>{m.organization.verified&&<Badge><ShieldCheck/>Verified</Badge>}</div></div>)}</CardContent></Card></div></>}
