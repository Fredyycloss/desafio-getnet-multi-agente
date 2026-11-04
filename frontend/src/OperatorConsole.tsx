import { useEffect, useState } from 'react'

type TicketMessage = { role: string; content: string; created_at: string }
type Ticket = {
  protocol: string; status: string; severity: string; reason: string; language: string; user_id: string
  assigned_operator?: string | null; operator_summary?: string | null; summary: string; created_at: string; updated_at: string
  messages: TicketMessage[]
}
type OperatorAuth = { token: string; username: string; display_name: string; role: string }

const KEY = 'getnet-operator-auth'
const STATUS: Record<string, string> = { queued: 'Aguardando', assigned: 'Em atendimento', resolved: 'Resolvido', returned_to_ai: 'Devolvido à IA' }

function load(): OperatorAuth | null {
  try { const raw = sessionStorage.getItem(KEY); return raw ? JSON.parse(raw) as OperatorAuth : null } catch { return null }
}
function save(auth: OperatorAuth | null) {
  try { if (auth) sessionStorage.setItem(KEY, JSON.stringify(auth)); else sessionStorage.removeItem(KEY) } catch { /* storage unavailable */ }
}

function OperatorLogin({ onLogin }: { onLogin: (a: OperatorAuth) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  async function submit() {
    setError('')
    const response = await fetch('/api/operator/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) })
    if (response.status === 429) { setError('Muitas tentativas. Aguarde e tente de novo.'); return }
    if (!response.ok) { setError('Usuário ou senha inválidos.'); return }
    const body = await response.json()
    onLogin({ token: body.access_token, username: body.username, display_name: body.display_name, role: body.role })
  }
  return <div className="login-shell"><form className="login-card" onSubmit={e => { e.preventDefault(); void submit() }} aria-label="Login de operador">
    <h1>Console de atendimento</h1>
    <p className="login-note">Acesso individual de operador. Toda ação fica registrada na auditoria.</p>
    <label className="login-pin">Usuário<input value={username} onChange={e => setUsername(e.target.value)} aria-label="Usuário" autoComplete="username"/></label>
    <label className="login-pin">Senha<input type="password" value={password} onChange={e => setPassword(e.target.value)} aria-label="Senha" autoComplete="current-password"/></label>
    {error && <div className="login-error" role="alert">{error}</div>}
    <button className="login-submit" type="submit" disabled={!username || !password}>Entrar</button>
  </form></div>
}

export default function OperatorConsole() {
  const [auth, setAuth] = useState<OperatorAuth | null>(() => load())
  const [queue, setQueue] = useState<Ticket[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [notice, setNotice] = useState('')
  const headers = auth ? { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}` } : undefined

  async function refresh() {
    if (!auth) return
    const response = await fetch('/api/operator/queue', { headers })
    if (response.status === 401) { save(null); setAuth(null); return }
    if (response.ok) setQueue((await response.json()).items)
  }
  useEffect(() => { void refresh(); const id = setInterval(() => void refresh(), 3000); return () => clearInterval(id) }, [auth]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!auth) return <OperatorLogin onLogin={a => { save(a); setAuth(a) }}/>
  const ticket = queue.find(t => t.protocol === selected) || null

  async function act(path: string, body: object, done: string) {
    if (!ticket) return
    const response = await fetch(`/api/operator/tickets/${encodeURIComponent(ticket.protocol)}/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
    const data = await response.json().catch(() => ({}))
    setNotice(response.ok ? done : `Não foi possível: ${typeof data.detail === 'string' ? data.detail : response.status}`)
    if (response.ok) setText('')
    void refresh()
  }

  return <div className="operator-shell">
    <header className="operator-top"><strong>Console de atendimento</strong><span>{auth.display_name} · {auth.role}</span>
      <button className="link-btn" onClick={() => { save(null); setAuth(null) }}>Sair</button></header>
    <div className="operator-body">
      <section className="operator-queue" aria-label="Fila de atendimento">
        <h2>Fila ({queue.length})</h2>
        {queue.map(t => <button key={t.protocol} className={`operator-item ${selected === t.protocol ? 'selected' : ''} sev-${t.severity}`} onClick={() => setSelected(t.protocol)}>
          <strong>{t.protocol}</strong><span>{STATUS[t.status] || t.status} · {t.severity}</span><small>{t.reason}</small>
        </button>)}
      </section>
      <section className="operator-detail" aria-label="Detalhes do atendimento">
        {!ticket ? <p>Selecione um atendimento.</p> : <>
          <h2>{ticket.protocol} <span className="operator-status">{STATUS[ticket.status] || ticket.status}</span></h2>
          <p><b>Resumo:</b> {ticket.operator_summary || ticket.summary}</p>
          <p><b>Responsável:</b> {ticket.assigned_operator || '—'}</p>
          <div className="operator-messages">{ticket.messages.map((m, i) => <div key={i} className={`operator-msg role-${m.role}`}><b>{m.role === 'user' ? 'Cliente' : m.role === 'operator' ? 'Atendente' : 'Assistente'}:</b> {m.content}</div>)}</div>
          <textarea value={text} onChange={e => setText(e.target.value)} placeholder="Mensagem, resolução ou instrução para a IA" aria-label="Texto do operador" rows={3}/>
          <div className="operator-actions">
            <button onClick={() => void act('claim', {}, 'Atendimento assumido.')} disabled={ticket.status !== 'queued'}>Assumir</button>
            <button onClick={() => void act('messages', { message: text }, 'Mensagem enviada ao cliente.')} disabled={!text || ticket.status !== 'assigned'}>Responder</button>
            <button onClick={() => void act('resolve', { resolution: text }, 'Atendimento resolvido.')} disabled={!text || ticket.status !== 'assigned'}>Resolver</button>
            <button onClick={() => void act('return-to-ai', { instruction: text }, 'Devolvido à IA com a instrução.')} disabled={!text || ticket.status !== 'assigned'}>Devolver para a IA</button>
          </div>
          {notice && <p className="operator-notice" role="status">{notice}</p>}
        </>}
      </section>
    </div>
  </div>
}
