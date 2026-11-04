import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUpRight, ChevronDown, CircleHelp, Headphones, LogOut, Menu, MessageCircle, Plus, Send, ShieldCheck, Sparkles, X, Zap } from 'lucide-react'

type Source = { title: string; url: string }
type ClarificationOption = { id: string; label: string }
type Reply = {
  answer: string
  language?: 'pt' | 'en'
  intent: string
  agent: string
  confidence: number
  sources?: Source[]
  handoff: boolean
  trace: string[]
  retrieved_chunks?: number
  handoff_protocol?: string
  handoff_status?: string
  handoff_severity?: string
  risk_level?: string
  real_agent_connected?: boolean
  orchestration_mode?: string
  tool_calls?: number
  trace_id?: string
  clarification_options?: ClarificationOption[]
  pending_action?: PendingAction
  action_protocol?: string
  critic?: { approved?: boolean; mode?: string; issues?: string[] }
  context_assessment?: { intent?: string; confidence?: number; ambiguity_level?: string; risk_level?: string; recommended_action?: string; recommended_destination?: string; operational_reason?: string }
}
type PendingAction = { action_id: string; kind: string; summary: string; status: string; expires_at: string; confirmation_token?: string
  requires_typed_confirmation?: boolean; typed_confirmation_phrase?: string; ttl_minutes?: number }
type Message = { id: string; role: 'assistant' | 'user'; text: string; meta?: Reply; time: string; author?: string; operator?: string }
type LiveMessage = { id: number; role: string; content: string; author?: string; operator?: string; handoff_status?: string }

const suggestions = [
  { icon: '▣', title: 'Máquinas Getnet', text: 'Qual a diferença entre a Get Clássica e a Get Smart?' },
  { icon: '↗', title: 'Recebimento de vendas', text: 'Quando recebo o dinheiro das minhas vendas?' },
  { icon: '⌁', title: 'Problemas de conexão', text: 'Minha maquininha não conecta à internet. O que faço?' },
  { icon: '◈', title: 'Link de pagamento', text: 'Posso vender pelo WhatsApp usando link de pagamento?' },
]
type Auth = { token: string; userId: string }
type DemoUser = { user_id: string; merchant_name: string; demo_pin: string }
const AUTH_KEY = 'getnet-assist-auth'
function loadAuth(): Auth | null {
  try { const raw = sessionStorage.getItem(AUTH_KEY); return raw ? JSON.parse(raw) as Auth : null } catch { return null }
}
function saveAuth(auth: Auth | null) {
  try { if (auth) sessionStorage.setItem(AUTH_KEY, JSON.stringify(auth)); else sessionStorage.removeItem(AUTH_KEY) } catch { /* storage unavailable */ }
}

function LoginScreen({ onLogin }: { onLogin: (auth: Auth) => void }) {
  const [users, setUsers] = useState<DemoUser[]>([])
  const [userId, setUserId] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // DEMO_MODE=false: the API does not list accounts (404) and the customer types the id.
  const [demo, setDemo] = useState(true)
  useEffect(() => {
    fetch('/api/auth/demo-users').then(r => {
      if (r.status === 404) { setDemo(false); return null }
      return r.json()
    }).then(body => {
      if (!body) return
      setUsers(body.users || [])
      if (body.users?.length) setUserId(body.users[0].user_id)
    }).catch(() => setError('Não consegui conectar à API.'))
  }, [])
  async function submit() {
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/auth/demo-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, pin }) })
      if (response.status === 429) { setError('Muitas tentativas. Aguarde alguns minutos e tente de novo.'); return }
      if (!response.ok) { setError('Usuário ou PIN inválido.'); return }
      const body = await response.json()
      onLogin({ token: body.access_token, userId: body.user_id })
    } catch { setError('Não consegui conectar à API.') } finally { setBusy(false) }
  }
  return <div className="login-shell"><form className="login-card" onSubmit={e => { e.preventDefault(); void submit() }} aria-label="Login demo">
    <div className="brand-row"><div className="brand-mark"><span>g</span></div><div className="brand-name">getnet<span>assist</span></div></div>
    <h1>{demo ? 'Entrar na demonstração' : 'Entrar'}</h1>
    {demo ? <>
      <p className="login-note">Contas sintéticas. O PIN de cada conta está listado de propósito: isto é uma demonstração, não autenticação de produção.</p>
      <div className="login-users" role="radiogroup" aria-label="Usuário sintético">
        {users.map(u => <label key={u.user_id} className={`login-user ${userId === u.user_id ? 'selected' : ''}`}>
          <input type="radio" name="user" value={u.user_id} checked={userId === u.user_id} onChange={() => setUserId(u.user_id)}/>
          <span><strong>{u.user_id}</strong><small>{u.merchant_name} · PIN {u.demo_pin}</small></span>
        </label>)}
      </div>
    </> : <label className="login-pin">Usuário<input value={userId} onChange={e => setUserId(e.target.value)} autoComplete="username" maxLength={128} aria-label="Usuário"/></label>}
    <label className="login-pin">PIN<input value={pin} onChange={e => setPin(e.target.value)} inputMode="numeric" autoComplete="off" maxLength={16} aria-label="PIN"/></label>
    {error && <div className="login-error" role="alert">{error}</div>}
    <button className="login-submit" type="submit" disabled={!userId || !pin || busy}>{busy ? 'Entrando…' : 'Entrar'}</button>
  </form></div>
}

const formatTime = () => new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(new Date())

export default function App() {
  const [auth, setAuth] = useState<Auth | null>(() => loadAuth())
  if (!auth) return <LoginScreen onLogin={a => { saveAuth(a); setAuth(a) }}/>
  return <Assistant auth={auth} onLogout={() => { saveAuth(null); setAuth(null) }}/>
}

function Assistant({ auth, onLogout }: { auth: Auth; onLogout: () => void }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [showDetails, setShowDetails] = useState<string | null>(null)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [mobileMenu, setMobileMenu] = useState(false)
  const userId = auth.userId
  const authHeaders = { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}` }
  function checkAuth(response: Response) { if (response.status === 401) onLogout() }
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID())
  const [activeHandoff, setActiveHandoff] = useState<{ protocol: string; language: 'pt' | 'en'; status: string } | null>(null)
  const lastSeenId = useRef(0)
  const HANDOFF_LABEL: Record<string, string> = { queued: 'aguardando atendente', assigned: 'em atendimento', resolved: 'resolvido', returned_to_ai: 'resolvido' }
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    fetch('/api/health').then(r => setApiOnline(r.ok)).catch(() => setApiOnline(false))
  }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  // Live updates while a human handles (or may pick up) the request: operator replies,
  // status changes, resolution summary and the assistant resuming after a hand-back.
  useEffect(() => {
    if (!activeHandoff || activeHandoff.status === 'resolved' || activeHandoff.status === 'returned_to_ai') return
    const poll = async () => {
      try {
        const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages?after_id=${lastSeenId.current}`, { headers: authHeaders })
        checkAuth(response)
        if (!response.ok) return
        const body: { messages: LiveMessage[]; last_message_id: number; ticket?: { status: string; real_agent_connected?: boolean } } = await response.json()
        lastSeenId.current = Math.max(lastSeenId.current, body.last_message_id || 0)
        const live = body.messages.filter(m => m.author && m.author !== 'assistant')
        if (live.length) setMessages(prev => [...prev, ...live.map(m => ({ id: `live-${m.id}`, role: 'assistant' as const, text: m.content, time: formatTime(), author: m.author, operator: m.operator }))])
        if (body.ticket?.status && body.ticket.status !== activeHandoff.status) setActiveHandoff({ ...activeHandoff, status: body.ticket.status })
      } catch { /* transient; next poll retries */ }
    }
    const id = setInterval(() => void poll(), 3000)
    return () => clearInterval(id)
  }, [activeHandoff, sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  const [typed, setTyped] = useState('')
  const [decided, setDecided] = useState<Record<string, boolean>>({})
  async function decideAction(action: PendingAction, decision: 'confirm' | 'cancel') {
    if (!action.confirmation_token) return
    setBusy(true)
    try {
      const response = await fetch(`/api/actions/${encodeURIComponent(action.action_id)}/${decision}`, {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ session_id: sessionId, confirmation_token: action.confirmation_token, typed_confirmation: typed || undefined }),
      })
      const data: Reply = await response.json()
      if (!response.ok) throw new Error('action')
      if (data.intent !== 'action_needs_typed_confirmation') setDecided(prev => ({ ...prev, [action.action_id]: true }))
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: data.answer, meta: data, time: formatTime() }])
      setTyped('')
    } catch {
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: 'Não consegui registrar sua decisão agora. Nada foi executado; tente de novo.', time: formatTime() }])
    } finally { setBusy(false) }
  }

  async function sendMessage(value = input, options: { humanRequest?: boolean } = {}) {
    const message = value.trim()
    if (!message || busy) return
    const humanRequest = options.humanRequest === true
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: message, time: formatTime() }])
    setInput('')
    setBusy(true)
    try {
      const response = await fetch('/api/chat', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ message, user_id: userId, session_id: sessionId }),
      })
      checkAuth(response)
      if (!response.ok) throw new Error(`${humanRequest ? 'handoff' : 'chat'}:${response.status}`)
      const data: Reply & { session_id?: string; last_message_id?: number } = await response.json()
      if (data.session_id) setSessionId(data.session_id)
      if (data.last_message_id) lastSeenId.current = Math.max(lastSeenId.current, data.last_message_id)
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: data.answer, meta: data, time: formatTime() }])
      if (data.handoff_protocol) {
        setActiveHandoff({ protocol: data.handoff_protocol, language: data.language === 'en' ? 'en' : 'pt', status: data.handoff_status || 'queued' })
      }
      setApiOnline(true)
    } catch (error) {
      setApiOnline(false)
      const failedHandoff = humanRequest || (error instanceof Error && error.message.startsWith('handoff:'))
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(), role: 'assistant',
        text: failedHandoff
          ? 'Não consegui confirmar o registro da solicitação de atendimento. Ela pode não ter sido registrada; tente novamente ou use os canais oficiais da Getnet.'
          : 'Não consegui conectar ao serviço agora. Confira se a API está em execução e tente novamente.',
        time: formatTime(),
      }])
    } finally {
      setBusy(false)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }

  async function requestHuman() {
    if (activeHandoff) {
      setBusy(true)
      try {
        const response = await fetch(`/api/handoffs/${encodeURIComponent(activeHandoff.protocol)}`, { headers: authHeaders })
        checkAuth(response)
        if (!response.ok) throw new Error(`handoff:${response.status}`)
        const ticket = await response.json()
        const status = String(ticket.status || activeHandoff.status)
        setActiveHandoff({ ...activeHandoff, status })
        setMessages(prev => [...prev, {
          id: crypto.randomUUID(), role: 'assistant',
          text: activeHandoff.language === 'en'
            ? `Support request ${activeHandoff.protocol} status: ${status}. ${ticket.real_agent_connected ? 'An attendant is connected.' : 'No live human attendant is connected to this demo.'}`
            : `Status da solicitação ${activeHandoff.protocol}: ${HANDOFF_LABEL[status] || status}. ${ticket.real_agent_connected ? 'Há atendente conectado ao canal de atendimento.' : 'Nenhum atendente conectado no momento; a solicitação segue na fila.'}`,
          time: formatTime(),
        }])
        setApiOnline(true)
      } catch {
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: 'Não consegui consultar o status desta solicitação agora. O protocolo permanece registrado; tente novamente em instantes.', time: formatTime() }])
        setApiOnline(false)
      } finally {
        setBusy(false)
      }
      return
    }
    await sendMessage('Quero falar com atendimento humano.', { humanRequest: true })
  }

  function newConversation() {
    setMessages([]); setInput(''); setActiveHandoff(null); setSessionId(crypto.randomUUID()); setMobileMenu(false); inputRef.current?.focus()
  }
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void sendMessage() }
  }

  return <div className="app-shell">
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>
      <div className="brand-row"><div className="brand-mark"><span>g</span></div><div className="brand-name">getnet<span>assist</span></div><button className="icon-btn mobile-close" onClick={() => setMobileMenu(false)} aria-label="Fechar menu"><X size={18}/></button></div>
      <button className="new-chat" onClick={newConversation}><Plus size={17}/><span>Nova conversa</span><span className="shortcut">⌘ K</span></button>
      <div className="side-label">SEU ESPAÇO</div>
      <button className="side-link active"><MessageCircle size={17}/><span>Assistente</span><span className="active-dot"/></button>
      <button className="side-link" onClick={() => void sendMessage('Quais soluções de pagamento a Getnet oferece?')}><Sparkles size={17}/><span>Explorar soluções</span><ArrowUpRight size={14} className="side-arrow"/></button>
      <div className="side-label help-label">COMO PODEMOS AJUDAR?</div>
      <button className="topic-link" onClick={() => void sendMessage('Quero saber sobre as maquininhas Getnet.')}><span className="topic-icon red">▣</span>Máquinas e equipamentos</button>
      <button className="topic-link" onClick={() => void sendMessage('Como funcionam os recebimentos das vendas?')}><span className="topic-icon navy">↗</span>Vendas e recebimentos</button>
      <button className="topic-link" onClick={() => void sendMessage('Quais são as soluções digitais da Getnet?')}><span className="topic-icon gold">◈</span>Soluções digitais</button>
      <div className="sidebar-bottom"><div className="support-card"><div className="support-icon"><Headphones size={18}/></div><div><strong>Precisa de mais ajuda?</strong><p>Estamos aqui para orientar.</p><a href="https://www.getnet.net/" target="_blank" rel="noreferrer">Acesse a Getnet oficial <ArrowUpRight size={12}/></a></div></div><div className="profile-row"><div className="avatar">G</div><div className="profile-copy"><strong>{userId}</strong><span>Conta sintética de demonstração</span></div><button className="icon-btn logout-btn" onClick={onLogout} aria-label="Sair"><LogOut size={15}/></button></div></div>
    </aside>
    {mobileMenu && <button className="mobile-backdrop" onClick={() => setMobileMenu(false)} aria-label="Fechar menu"/>}
    <main className="main-area">
      <header className="topbar">
        <div className="top-left"><button className="icon-btn mobile-menu-btn" onClick={() => setMobileMenu(true)} aria-label="Abrir menu"><Menu size={20}/></button><div className="breadcrumb">Assistente <span>/</span> <strong>Nova conversa</strong></div></div>
        <div className="top-actions">
          <button className={`human-request-btn ${activeHandoff ? 'registered' : ''}`} onClick={requestHuman} disabled={busy} aria-label={activeHandoff ? 'Consultar solicitação de atendimento' : 'Falar com atendente'}>
            <Headphones size={15}/>{activeHandoff ? 'Status do atendimento' : 'Falar com atendente'}
          </button>
          <div className={`status-pill ${apiOnline === false ? 'offline' : ''}`}><span className="status-dot"/>{apiOnline === null ? 'Conectando' : apiOnline ? 'Sistema operacional' : 'API desconectada'}</div>
          <button className="top-help" onClick={() => void sendMessage('Como você pode me ajudar?')}><CircleHelp size={16}/><span>Ajuda</span></button>
        </div>
      </header>
      <section className={`workspace ${messages.length ? 'workspace-chatting' : ''}`}>
        {messages.length === 0 ? <div className="welcome-wrap"><div className="eyebrow"><span className="eyebrow-line"/><Sparkles size={13}/><span>INTELIGÊNCIA QUE MOVE NEGÓCIOS</span></div><div className="welcome-heading"><h1>Seu negócio tem<br/>muito a <span>conquistar.</span></h1><p>Oi! Eu sou o assistente Getnet.<br/>Como posso facilitar o seu dia hoje?</p></div><div className="suggestion-grid">{suggestions.map((s, i) => <button className="suggestion-card" key={s.title} onClick={() => void sendMessage(s.text)}><div className={`suggestion-icon tone-${i}`}>{s.icon}</div><div className="suggestion-copy"><strong>{s.title}</strong><span>{s.text}</span></div><ArrowUpRight size={16} className="suggestion-arrow"/></button>)}</div><div className="trust-row"><div className="trust-icon"><ShieldCheck size={17}/></div><div><strong>Informação com responsabilidade</strong><span>Respostas orientativas, com base em fontes disponíveis.</span></div><div className="trust-divider"/><div className="trust-icon"><Zap size={16}/></div><div><strong>Feito para você</strong><span>Entende o contexto da sua pergunta.</span></div></div></div> : <div className="conversation">
          <div className="conversation-intro"><div className="conversation-spark"><Sparkles size={15}/></div><div><strong>Vamos resolver juntos.</strong><span>Conversa com Getnet Assist</span></div><button className="new-small" onClick={newConversation}><Plus size={14}/> Nova conversa</button></div>
          {messages.map(msg => <div className={`message-row ${msg.role} ${msg.author === 'operator' ? 'operator' : ''}`} key={msg.id}>
            {msg.role === 'assistant' ? <div className="message-avatar"><span>{msg.author === 'operator' ? 'A' : 'g'}</span></div> : <div className="user-avatar">V</div>}
            <div className="message-content">
              <div className="message-meta"><strong>{msg.role === 'assistant' ? (msg.author === 'operator' ? 'Atendente' : 'Getnet Assist') : 'Você'}</strong>{msg.author === 'operator' && msg.operator && <span className="author-badge">{msg.operator}</span>}<span>{msg.time}</span></div>
              <div className={`message-bubble ${msg.role}`}>{msg.text.split('\n').map((line, i) => line ? <p key={i}>{line}</p> : <div key={i} className="line-space"/>)}</div>
              {msg.meta?.clarification_options && <div className="clarification-actions" aria-label="Opções para continuar">{msg.meta.clarification_options.map((option, index) => <button key={option.id} className="clarification-option" onClick={() => void sendMessage(option.label)} disabled={busy}>{index + 1}. {option.label}</button>)}</div>}
              {msg.meta?.pending_action && !decided[msg.meta.pending_action.action_id] && <div className="action-card" aria-label="Confirmar ação">
                <strong>{msg.meta.language === 'en' ? 'Confirmation needed' : 'Confirmação necessária'}</strong>
                <p>{msg.meta.pending_action.summary}</p>
                {msg.meta.pending_action.requires_typed_confirmation && <label className="action-typed">{msg.meta.language === 'en' ? 'Type' : 'Digite'} “{msg.meta.pending_action.typed_confirmation_phrase}”
                  <input value={typed} onChange={e => setTyped(e.target.value)} aria-label="Frase de confirmação" autoComplete="off"/></label>}
                <div className="action-buttons">
                  <button className="action-confirm" onClick={() => void decideAction(msg.meta!.pending_action!, 'confirm')} disabled={busy}>{msg.meta.language === 'en' ? 'Confirm' : 'Confirmar'}</button>
                  <button className="action-cancel" onClick={() => void decideAction(msg.meta!.pending_action!, 'cancel')} disabled={busy}>{msg.meta.language === 'en' ? 'Cancel' : 'Cancelar'}</button>
                </div>
              </div>}
              {msg.meta?.action_protocol && <div className="action-done">Protocolo da ação: <b>{msg.meta.action_protocol}</b></div>}
              {(msg.meta?.sources?.length ?? 0) > 0 && <div className="inline-sources"><span>Fontes consultadas</span>{msg.meta?.sources?.slice(0, 3).map(source => <a href={source.url} target="_blank" rel="noreferrer" key={source.url + source.title}>{source.title}<ArrowUpRight size={12}/></a>)}</div>}
              {msg.meta && <>
                <button className="detail-toggle" onClick={() => setShowDetails(showDetails === msg.id ? null : msg.id)}><Sparkles size={13}/>{msg.meta.agent.replace(/_/g, ' ')}<ChevronDown size={13} className={showDetails === msg.id ? 'rotate' : ''}/></button>
                {showDetails === msg.id && <div className="agent-details">
                  <div><span>Idioma da resposta</span><strong>{msg.meta.language === 'en' ? 'English' : 'Português'}</strong></div>
                  <div><span>Intenção identificada</span><strong>{msg.meta.intent.replace(/_/g, ' ')}</strong></div>
                  <div><span>Confiança estimada</span><strong>{Math.round(msg.meta.confidence * 100)}%</strong></div>
                  {msg.meta.context_assessment?.recommended_destination && <div><span>Direcionamento</span><strong>{msg.meta.context_assessment.recommended_destination.replace(/_/g, ' ')}</strong></div>}
                  {msg.meta.orchestration_mode && <div><span>Orquestração</span><strong>{msg.meta.orchestration_mode.replace(/_/g, ' ')}</strong></div>}
                  {typeof msg.meta.tool_calls === 'number' && <div><span>Chamadas de ferramentas</span><strong>{msg.meta.tool_calls}</strong></div>}
                  {msg.meta.critic && <div><span>Revisão independente</span><strong>{msg.meta.critic.approved ? 'Aprovada' : 'Requer revisão'} · {msg.meta.critic.mode}</strong></div>}
                  {typeof msg.meta.retrieved_chunks === 'number' && <div><span>Trechos recuperados</span><strong>{msg.meta.retrieved_chunks}</strong></div>}
                  <div className="trace-row"><span>Fluxo de agentes</span><div>{msg.meta.trace.map((t, i) => <span className="trace-chip" key={`${t}-${i}`}>{t.replace(/_/g, ' ')}</span>)}</div></div>
                  {(msg.meta.sources?.length ?? 0) > 0 && <div className="source-list"><span>Fontes consultadas</span>{msg.meta.sources?.map(s => <a href={s.url} target="_blank" rel="noreferrer" key={s.url+s.title}>{s.title}<ArrowUpRight size={12}/></a>)}</div>}
                  {msg.meta.handoff && <div className={`handoff-note ${msg.meta.handoff_severity === 'critical' || msg.meta.handoff_severity === 'high' ? 'handoff-critical' : ''}`}><Headphones size={15}/><div className="handoff-copy"><strong>{msg.meta.language === 'en' ? 'Human-support request registered' : 'Solicitação de atendimento registrada'}</strong>{msg.meta.handoff_protocol && <p><b>Protocolo: {msg.meta.handoff_protocol}</b></p>}<p>{msg.meta.handoff_status === 'queued' ? 'Status: aguardando atendimento.' : `Status: ${msg.meta.handoff_status || 'registrado'}.`} {msg.meta.real_agent_connected === false ? 'Nenhum atendente real está conectado a esta demonstração.' : 'Encaminhamento informado pelo serviço.'}</p>{msg.meta.handoff_protocol && <button className="link-btn" onClick={() => void requestHuman()} disabled={busy}>Consultar protocolo <ArrowUpRight size={12}/></button>}</div></div>}
                </div>}
              </>}
            </div>
          </div>)}
          {busy && <div className="message-row assistant"><div className="message-avatar"><span>g</span></div><div className="message-content"><div className="message-meta"><strong>Getnet Assist</strong><span>pensando</span></div><div className="typing-bubble"><span/><span/><span/></div></div></div>}
          <div ref={bottomRef}/>
        </div>}
      </section>
      <footer className={`composer-area ${messages.length ? 'composer-chatting' : ''}`}><div className="composer"><textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKeyDown} placeholder={activeHandoff ? 'Escreva uma atualização para a solicitação...' : 'Escreva sua pergunta aqui...'} rows={1} maxLength={2000} aria-label="Sua pergunta"/><div className="composer-bottom"><div className="composer-hint"><span className="keyboard-enter">↵</span><span>Enter para enviar</span><span className="hint-divider">·</span><span>Shift + Enter para nova linha</span></div><div className="composer-right"><span className="char-count">{input.length}/2000</span><button className="send-btn" onClick={() => void sendMessage()} disabled={!input.trim() || busy} aria-label="Enviar mensagem">{busy ? <span className="send-spinner"/> : <Send size={16}/>}</button></div></div></div><div className="disclaimer"><ShieldCheck size={12}/><span>Demonstração técnica: a conta {userId} e os registros são sintéticos. Não compartilhe senhas ou dados de cartão.</span></div></footer>
    </main>
  </div>
}
