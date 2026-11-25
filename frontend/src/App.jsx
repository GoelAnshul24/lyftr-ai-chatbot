import { useEffect, useRef, useState } from 'react'
import { API_URL, sendChat } from './api.js'

// A new session on every page load.
function newSessionId() {
  const id = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2)
  return 's-' + id.slice(0, 8)
}

const SIMULATE_OPTIONS = [
  { value: '', label: 'Simulate failure: off' },
  { value: 'key_1=429', label: 'key_1=429 (fail over to key_2)' },
  { value: 'key_1=500', label: 'key_1=500 (fail over to key_2)' },
  { value: '*=429', label: '*=429 (all keys fail)' },
]

function AssistantMessage({ item }) {
  const m = item.meta
  const cached = m.resolution_source === 'LLM_CACHE'
  return (
    <div className="row assistant">
      <div className="bubble" data-testid="assistant-message">
        <div className="text">{item.text}</div>
        <div className="meta">
          <span className={`badge ${cached ? 'cache' : 'live'}`} data-testid="meta-source">
            {m.resolution_source}
          </span>
          <span className="chip"><span className="lbl">model</span> <span data-testid="meta-model">{m.model}</span></span>
          <span className="chip"><span className="lbl">latency</span> <span data-testid="meta-latency">{m.latency_ms} ms</span></span>
          <span className="chip"><span className="lbl">in</span> <span data-testid="meta-input-tokens">{m.input_tokens}</span></span>
          <span className="chip"><span className="lbl">out</span> <span data-testid="meta-output-tokens">{m.output_tokens}</span></span>
        </div>
        <div className="meta small">
          key: {m.key_id ?? 'none (cache hit)'} &middot; fallback attempts: {m.fallback_attempts}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [sessionId] = useState(newSessionId)
  const [items, setItems] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [simulate, setSimulate] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)
  const inputRef = useRef(null)
  const nextId = useRef(0)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items, loading])

  const add = (item) => setItems((prev) => [...prev, { id: nextId.current++, ...item }])

  async function send() {
    if (loading || !input.trim()) return // ignore empty / whitespace-only (backend still validates with 422)
    const message = input
    setInput('') // empty after sending
    add({ kind: 'user', text: message.trim() })
    setLoading(true)
    try {
      const data = await sendChat({ sessionId, message, systemPrompt, simulate })
      add({ kind: 'assistant', text: data.reply, meta: data.metadata })
    } catch (err) {
      add({ kind: 'error', text: err.message }) // never shown as an assistant reply
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Lyftr AI Chatbot</h1>
        <span className="session">session {sessionId}</span>
      </header>

      <div className="controls">
        <input
          type="text"
          className="sys"
          data-testid="system-prompt-input"
          placeholder="Optional system prompt for this session (e.g. 'Answer like a pirate')"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          aria-label="System prompt"
        />
        <select value={simulate} onChange={(e) => setSimulate(e.target.value)} aria-label="Simulate failure">
          {SIMULATE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <main className="messages" role="log" aria-live="polite">
        {items.length === 0 && !loading && (
          <p className="empty">Say hello. Each reply shows where it came from, the model, latency and tokens for that request.</p>
        )}
        {items.map((item) => {
          if (item.kind === 'assistant') return <AssistantMessage key={item.id} item={item} />
          if (item.kind === 'user') {
            return (
              <div className="row user" key={item.id}>
                <div className="bubble" data-testid="user-message">{item.text}</div>
              </div>
            )
          }
          return (
            <div className="row error" key={item.id}>
              <div className="bubble" role="alert" data-testid="error-message">{item.text}</div>
            </div>
          )
        })}
        {loading && (
          <div className="row assistant">
            <div className="bubble loading" data-testid="loading" aria-label="Waiting for reply">
              <span className="dot" /><span className="dot" /><span className="dot" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea
          ref={inputRef}
          data-testid="chat-input"
          rows={2}
          placeholder="Type a message. Enter sends, Shift+Enter adds a new line."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Message"
        />
        <button data-testid="send-button" onClick={send} disabled={loading || !input.trim()}>
          {loading ? 'Sending...' : 'Send'}
        </button>
      </footer>
      <div className="api">API: {API_URL}</div>
    </div>
  )
}
