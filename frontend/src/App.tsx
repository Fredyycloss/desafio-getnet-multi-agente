import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Bot, Check, ChevronDown, CircleHelp, Clock3, Headphones, Menu, MessageCircle, Plus, Send, ShieldCheck, Sparkles, X, Zap } from 'lucide-react'

type Source = { title: string; url: string }
type Reply = { answer: string; intent: string; agent: string; confidence: number; sources: Source[]; handoff: boolean; trace: string[] }
type Message = { id: string; role: 'assistant' | 'user'; text: string; meta?: Reply; time: string }
const suggestions = [
  { icon: '▣', title: 'Máquinas Getnet', text: 'Qual a diferença entre a Get Clássica e a Get Smart?' },
  { icon: '↗', title: 'Recebimento de vendas', text: 'Quando recebo o dinheiro das minhas vendas?' },
  { icon: '⌁', title: 'Problemas de conexão', text: 'Minha maquininha não conecta à internet. O que faço?' },
  { icon: '◈', title: 'Link de pagamento', text: 'Posso vender pelo WhatsApp usando link de pagamento?' },
]
const formatTime = () => new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(new Date())

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [showDetails, setShowDetails] = useState<string | null>(null)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [mobileMenu, setMobileMenu] = useState(false)
  const [userId] = useState(() => `visitante-${Math.random().toString(36).slice(2, 8)}`)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    fetch('/api/health').then(r => setApiOnline(r.ok)).catch(() => setApiOnline(false))
  }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  async function sendMessage(value = input) {
    const message = value.trim()
    if (!message || busy) return
    const userMessage: Message = { id: crypto.randomUUID(), role: 'user', text: message, time: formatTime() }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setBusy(true)
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, user_id: userId }) })
      if (!response.ok) throw new Error(`A API respondeu com status ${response.status}.`)
      const data: Reply = await response.json()
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: data.answer, meta: data, time: formatTime() }])
      setApiOnline(true)
    } catch {
      setApiOnline(false)
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: 'Não consegui conectar ao serviço agora. Confira se a API está em execução e tente novamente. Se estiver usando Docker, execute `docker compose up --build` na pasta do projeto.', time: formatTime() }])
    } finally {
      setBusy(false)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }
  function newConversation() { setMessages([]); setInput(''); setMobileMenu(false); inputRef.current?.focus() }
  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }

  return <div className="app-shell">
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>
      <div className="brand-row"><div className="brand-mark"><span>g</span></div><div className="brand-name">getnet<span>assist</span></div><button className="icon-btn mobile-close" onClick={() => setMobileMenu(false)} aria-label="Fechar menu"><X size={18}/></button></div>
      <button className="new-chat" onClick={newConversation}><Plus size={17}/><span>Nova conversa</span><span className="shortcut">⌘ K</span></button>
      <div className="side-label">SEU ESPAÇO</div>
      <button className="side-link active"><MessageCircle size={17}/><span>Assistente</span><span className="active-dot"/></button>
      <button className="side-link" onClick={() => sendMessage('Quais soluções de pagamento a Getnet oferece?')}><Sparkles size={17}/><span>Explorar soluções</span><ArrowUpRight size={14} className="side-arrow"/></button>
      <div className="side-label help-label">COMO PODEMOS AJUDAR?</div>
      <button className="topic-link" onClick={() => sendMessage('Quero saber sobre as maquininhas Getnet.')}><span className="topic-icon red">▣</span>Máquinas e equipamentos</button>
      <button className="topic-link" onClick={() => sendMessage('Como funcionam os recebimentos das vendas?')}><span className="topic-icon navy">↗</span>Vendas e recebimentos</button>
      <button className="topic-link" onClick={() => sendMessage('Quais são as soluções digitais da Getnet?')}><span className="topic-icon gold">◈</span>Soluções digitais</button>
      <div className="sidebar-bottom"><div className="support-card"><div className="support-icon"><Headphones size={18}/></div><div><strong>Precisa de mais ajuda?</strong><p>Estamos aqui para orientar.</p><a href="https://www.getnet.net/" target="_blank" rel="noreferrer">Acesse a Getnet oficial <ArrowUpRight size={12}/></a></div></div><div className="profile-row"><div className="avatar">G</div><div className="profile-copy"><strong>Visitante</strong><span>Assistente virtual</span></div><span className="profile-menu">•••</span></div></div>
    </aside>
    {mobileMenu && <button className="mobile-backdrop" onClick={() => setMobileMenu(false)} aria-label="Fechar menu"/>}
    <main className="main-area">
      <header className="topbar"><div className="top-left"><button className="icon-btn mobile-menu-btn" onClick={() => setMobileMenu(true)} aria-label="Abrir menu"><Menu size={20}/></button><div className="breadcrumb">Assistente <span>/</span> <strong>Nova conversa</strong></div></div><div className="top-actions"><div className={`status-pill ${apiOnline === false ? 'offline' : ''}`}><span className="status-dot"/>{apiOnline === null ? 'Conectando' : apiOnline ? 'Sistema operacional' : 'API desconectada'}</div><button className="top-help" onClick={() => sendMessage('Como você pode me ajudar?')}><CircleHelp size={16}/><span>Ajuda</span></button></div></header>
      <section className={`workspace ${messages.length ? 'workspace-chatting' : ''}`}>
        {messages.length === 0 ? <div className="welcome-wrap"><div className="eyebrow"><span className="eyebrow-line"/><Sparkles size={13}/><span>INTELIGÊNCIA QUE MOVE NEGÓCIOS</span></div><div className="welcome-heading"><h1>Seu negócio tem<br/>muito a <span>conquistar.</span></h1><p>Oi! Eu sou o assistente Getnet.<br/>Como posso facilitar o seu dia hoje?</p></div><div className="suggestion-grid">{suggestions.map((s, i) => <button className="suggestion-card" key={s.title} onClick={() => sendMessage(s.text)}><div className={`suggestion-icon tone-${i}`}>{s.icon}</div><div className="suggestion-copy"><strong>{s.title}</strong><span>{s.text}</span></div><ArrowUpRight size={16} className="suggestion-arrow"/></button>)}</div><div className="trust-row"><div className="trust-icon"><ShieldCheck size={17}/></div><div><strong>Informação com responsabilidade</strong><span>Respostas orientativas, com base em fontes disponíveis.</span></div><div className="trust-divider"/><div className="trust-icon"><Zap size={16}/></div><div><strong>Feito para você</strong><span>Entende o contexto da sua pergunta.</span></div></div></div> : <div className="conversation"><div className="conversation-intro"><div className="conversation-spark"><Sparkles size={15}/></div><div><strong>Vamos resolver juntos.</strong><span>Conversa com Getnet Assist</span></div><button className="new-small" onClick={newConversation}><Plus size={14}/> Nova conversa</button></div>{messages.map(msg => <div className={`message-row ${msg.role}`} key={msg.id}>{msg.role === 'assistant' ? <div className="message-avatar"><span>g</span></div> : <div className="user-avatar">V</div>}<div className="message-content"><div className="message-meta"><strong>{msg.role === 'assistant' ? 'Getnet Assist' : 'Você'}</strong><span>{msg.time}</span></div><div className={`message-bubble ${msg.role}`}>{msg.text.split('\n').map((line, i) => line ? <p key={i}>{line}</p> : <div key={i} className="line-space"/> )}</div>{msg.meta && <><button className="detail-toggle" onClick={() => setShowDetails(showDetails === msg.id ? null : msg.id)}><Sparkles size={13}/>{msg.meta.agent.replaceAll('_', ' ')}<ChevronDown size={13} className={showDetails === msg.id ? 'rotate' : ''}/></button>{showDetails === msg.id && <div className="agent-details"><div><span>Intenção identificada</span><strong>{msg.meta.intent.replaceAll('_', ' ')}</strong></div><div><span>Confiança estimada</span><strong>{Math.round(msg.meta.confidence * 100)}%</strong></div><div className="trace-row"><span>Fluxo de agentes</span><div>{msg.meta.trace.map((t, i) => <span className="trace-chip" key={`${t}-${i}`}>{t.replaceAll('_', ' ')}</span>)}</div></div>{msg.meta.sources.length > 0 && <div className="source-list"><span>Fontes consultadas</span>{msg.meta.sources.map(s => <a href={s.url} target="_blank" rel="noreferrer" key={s.url+s.title}>{s.title}<ArrowUpRight size={12}/></a>)}</div>}{msg.meta.handoff && <div className="handoff-note"><Headphones size={14}/> Recomendado atendimento humano</div>}</div>}</>}</div></div>)}{busy && <div className="message-row assistant"><div className="message-avatar"><span>g</span></div><div className="message-content"><div className="message-meta"><strong>Getnet Assist</strong><span>pensando</span></div><div className="typing-bubble"><span/><span/><span/></div></div></div>}<div ref={bottomRef}/></div>}
      </section>
      <footer className={`composer-area ${messages.length ? 'composer-chatting' : ''}`}><div className="composer"><textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKeyDown} placeholder="Escreva sua pergunta aqui..." rows={1} maxLength={2000} aria-label="Sua pergunta"/><div className="composer-bottom"><div className="composer-hint"><span className="keyboard-enter">↵</span><span>Enter para enviar</span><span className="hint-divider">·</span><span>Shift + Enter para nova linha</span></div><div className="composer-right"><span className="char-count">{input.length}/2000</span><button className="send-btn" onClick={() => sendMessage()} disabled={!input.trim() || busy} aria-label="Enviar mensagem">{busy ? <span className="send-spinner"/> : <Send size={16}/>}</button></div></div></div><div className="disclaimer"><ShieldCheck size={12}/><span>Assistente demonstrativo. Não compartilhe dados pessoais, senhas ou informações de cartão.</span></div></footer>
    </main>
  </div>
}
