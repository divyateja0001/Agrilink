import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Loader2, RotateCcw, Send, ShieldCheck, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import type { AssistantConversation, AssistantMessage, ProcurementDraft } from '@/lib/types'

type AssistantProps = {
  quotationId?: string
  requirementId?: string
  trigger?: React.ReactNode
  onUseDraft?: (draft: ProcurementDraft) => void
}
type ConversationList = { role: 'buyer' | 'farmer' | 'fpo_manager'; items: AssistantConversation[] }
type MessageList = { conversation: AssistantConversation; items: AssistantMessage[] }
type SendResult = {
  conversation: AssistantConversation
  message: AssistantMessage
  result: { draft?: ProcurementDraft; suggestions: string[]; warnings: string[]; follow_up_questions: string[]; source: string; model: string }
}

const taskOptions = {
  buyer: [['general', 'askAgriLink'], ['draft_requirement', 'draftRequirementTask'], ['analyze', 'analyzeSuppliers'], ['draft_counter', 'draftCounter'], ['crop_guidance', 'cropGuidance']],
  farmer: [['general', 'askAgriLink'], ['draft_listing', 'draftListing'], ['find_demand', 'findDemand'], ['draft_quote', 'draftQuote'], ['crop_guidance', 'cropGuidance']],
  fpo_manager: [['general', 'askAgriLink'], ['draft_listing', 'draftListing'], ['find_demand', 'findDemand'], ['draft_quote', 'draftQuote'], ['plan_allocation', 'planAllocation'], ['crop_guidance', 'cropGuidance']],
} as const

export function ProcurementAssistant({ quotationId, requirementId, trigger, onUseDraft }: AssistantProps) {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [activeId, setActiveId] = useState('')
  const [message, setMessage] = useState('')
  const [mode, setMode] = useState(quotationId ? 'draft_counter' : requirementId ? 'analyze' : 'general')

  const conversations = useQuery({ queryKey: ['assistant-conversations'], queryFn: () => api<ConversationList>('/api/assistant/conversations'), enabled: open })
  const { mutate: createConversation, isPending: creating } = useMutation({
    mutationFn: () => api<AssistantConversation>('/api/assistant/conversations', { method: 'POST', body: JSON.stringify({ language: (i18n.resolvedLanguage || 'en').slice(0, 2) }) }),
    onSuccess: async (item) => { setActiveId(item.id); await qc.invalidateQueries({ queryKey: ['assistant-conversations'] }) },
    onError: (error: Error) => toast.error(error.message),
  })
  const conversationId = activeId || conversations.data?.items[0]?.id || ''

  useEffect(() => {
    if (open && !conversations.isLoading && conversations.data && !conversations.data.items.length && !creating && !activeId) createConversation()
  }, [open, conversations.isLoading, conversations.data, creating, activeId, createConversation])

  const messages = useQuery({ queryKey: ['assistant-messages', conversationId], queryFn: () => api<MessageList>(`/api/assistant/conversations/${conversationId}/messages`), enabled: open && Boolean(conversationId) })
  const send = useMutation({
    mutationFn: () => api<SendResult>(`/api/assistant/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ message, mode, requirement_id: requirementId, quotation_id: quotationId, language: (i18n.resolvedLanguage || 'en').slice(0, 2) }) }),
    onSuccess: async () => { setMessage(''); await Promise.all([qc.invalidateQueries({ queryKey: ['assistant-messages', conversationId] }), qc.invalidateQueries({ queryKey: ['assistant-conversations'] })]) },
    onError: (error: Error) => toast.error(error.message),
  })
  const reset = useMutation({
    mutationFn: () => api<AssistantConversation>(`/api/assistant/conversations/${conversationId}/reset`, { method: 'POST' }),
    onSuccess: async (item) => { setActiveId(item.id); setMessage(''); await qc.invalidateQueries({ queryKey: ['assistant-conversations'] }) },
    onError: (error: Error) => toast.error(error.message),
  })

  const role = conversations.data?.role || 'buyer'
  const latest = messages.data?.items.filter((item) => item.role === 'assistant').at(-1)
  const metadata = latest?.metadata || {}
  const draft = metadata.draft as ProcurementDraft | undefined
  const degraded = latest?.source === 'rule_based' && Boolean(metadata.degraded_reason)
  const warnings = Array.isArray(metadata.warnings) ? metadata.warnings as string[] : []
  const suggestions = Array.isArray(metadata.suggestions) ? metadata.suggestions as string[] : []
  const contextHint = useMemo(() => requirementId ? `Requirement ${requirementId.slice(0, 8)}: ` : quotationId ? `Negotiation ${quotationId.slice(0, 8)}: ` : '', [requirementId, quotationId])

  const useDraft = () => {
    if (!draft) return
    if (onUseDraft) { onUseDraft(draft); setOpen(false); return }
    localStorage.setItem('agrilink-requirement-draft', JSON.stringify(draft))
    window.location.assign(role === 'buyer' ? '/requirements?draft=assistant' : '/produce?draft=assistant')
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger ?? <Button variant="ghost" size="icon" aria-label={t('assistant')}><Sparkles /></Button>}</SheetTrigger>
      <SheetContent className="flex w-full flex-col gap-0 overflow-hidden p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        <SheetHeader className="border-b p-5 pr-14">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-primary p-2.5 text-primary-foreground"><Bot className="size-5" /></span>
            <div className="min-w-0 flex-1"><SheetTitle>{t('aiTitle')}</SheetTitle><SheetDescription>{t('aiHelp')}</SheetDescription></div>
            {conversationId ? <Button size="icon" variant="ghost" aria-label={t('resetChat')} title={t('resetChat')} onClick={() => reset.mutate()} disabled={reset.isPending}><RotateCcw /></Button> : null}
          </div>
        </SheetHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
          <Alert className="border-amber-300 bg-amber-50"><ShieldCheck className="text-amber-800" /><AlertTitle>{t('advisory')}</AlertTitle><AlertDescription>{t('assistantSafety')}</AlertDescription></Alert>
          <div className="grid min-w-0 gap-3 rounded-xl border bg-muted/25 p-3">
            <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground">
              {t('conversation')}
              <Select value={conversationId} onValueChange={setActiveId}><SelectTrigger className="w-full min-w-0 bg-background" aria-label={t('conversation')}><SelectValue placeholder={t('newConversation')} /></SelectTrigger><SelectContent>{conversations.data?.items.map((item) => <SelectItem key={item.id} value={item.id}>{item.title}</SelectItem>)}</SelectContent></Select>
            </label>
            <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground">
              {t('assistantTask')}
              <Select value={mode} onValueChange={setMode}><SelectTrigger className="w-full min-w-0 bg-background" aria-label={t('assistantTask')}><SelectValue /></SelectTrigger><SelectContent>{taskOptions[role].map(([value, label]) => <SelectItem key={value} value={value}>{t(label)}</SelectItem>)}</SelectContent></Select>
            </label>
          </div>

          <div className="min-h-48 space-y-3" aria-live="polite">
            {messages.isLoading ? <div className="flex justify-center py-10"><Loader2 className="animate-spin" /></div> : messages.data?.items.length ? messages.data.items.map((item) => (
              <Message key={item.id} from={item.role}><MessageContent className="max-w-[92%] rounded-2xl border p-3.5 shadow-xs"><MessageResponse>{item.content}</MessageResponse>{item.role === 'assistant' ? <p className="mt-2 text-[11px] text-muted-foreground">{item.source === 'mistral' ? `Mistral · ${item.model}` : t('ruleBasedFallback')}</p> : null}</MessageContent></Message>
            )) : <p className="py-10 text-center text-sm text-muted-foreground">{t('assistantEmpty')}</p>}
            {degraded ? <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><b>{t('ruleBasedFallback')}:</b> {t('liveAiUnavailable')}</p> : null}
            {!degraded && warnings.length ? <Alert variant="destructive"><AlertTitle>{t('checkRisks')}</AlertTitle><AlertDescription>{warnings.join(' · ')}</AlertDescription></Alert> : null}
            {suggestions.length ? <div className="rounded-xl border bg-muted/25 p-3"><p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('suggestionsLabel')}</p><ul className="space-y-1 text-sm">{suggestions.map((item) => <li key={item}>• {item}</li>)}</ul></div> : null}
            {draft ? <Card><CardContent className="space-y-3 p-4"><p className="font-medium">{t('reviewableDraft')}</p><dl className="grid grid-cols-2 gap-2 text-sm">{Object.entries(draft).filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => <div key={key}><dt className="text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="font-medium">{String(value)}</dd></div>)}</dl><Button className="w-full" onClick={useDraft}>{t('useDraft')}</Button></CardContent></Card> : null}
          </div>
        </div>

        <form className="space-y-2 border-t bg-background p-4 sm:p-5" onSubmit={(event) => { event.preventDefault(); if (message.trim()) send.mutate() }}>
          <Textarea value={message} onChange={(event) => setMessage(event.target.value)} maxLength={1000} rows={3} placeholder={t('aiPlaceholder')} aria-label={t('aiPlaceholder')} />
          <div className="flex items-center justify-between gap-3"><span className="text-xs text-muted-foreground">{message.length}/1000</span><Button disabled={!conversationId || !message.trim() || send.isPending}>{send.isPending ? <Loader2 className="animate-spin" /> : <Send />}{t('askAssistant')}</Button></div>
          {contextHint ? <p className="text-xs text-muted-foreground">{contextHint}{t('authorizedContext')}</p> : null}
        </form>
      </SheetContent>
    </Sheet>
  )
}

export default ProcurementAssistant
