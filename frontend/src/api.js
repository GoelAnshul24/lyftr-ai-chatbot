// Build-time setting (VITE_API_URL). Default is the local backend.
export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')

// ["body","message"] -> "message"; ["body", 29] (bad JSON) -> "request body"
function fieldName(loc = []) {
  const names = loc.filter((p) => typeof p === 'string' && p !== 'body')
  return names.length ? names.join('.') : 'request body'
}

// Turns a backend error (detail may be a string or a FastAPI validation array) into one readable line.
export function describeError(status, data) {
  const detail = data && data.detail
  if (Array.isArray(detail)) {
    const parts = detail.map((e) => `${fieldName(e.loc)}: ${e.msg}`)
    return `Invalid request (${status}) - ${parts.join('; ')}`
  }
  if (typeof detail === 'string' && detail) {
    if (status === 503) return `Service unavailable (503) - ${detail}. Please try again in a moment.`
    return `${detail} (${status})`
  }
  return `Request failed (HTTP ${status})`
}

export async function sendChat({ sessionId, message, systemPrompt, simulate }) {
  const headers = { 'Content-Type': 'application/json' }
  if (simulate) headers['X-Simulate-Failure'] = simulate
  const body = { session_id: sessionId, message }
  if (systemPrompt && systemPrompt.trim()) body.system_prompt = systemPrompt

  let res
  try {
    res = await fetch(`${API_URL}/chat`, { method: 'POST', headers, body: JSON.stringify(body) })
  } catch {
    throw new Error(`Cannot reach the server at ${API_URL}. Check that the backend is running and allows this site's origin.`)
  }

  let data = null
  try {
    data = await res.json()
  } catch {
    // non-JSON body: fall through to the generic message below
  }
  if (!res.ok) throw new Error(describeError(res.status, data))
  if (!data || typeof data.reply !== 'string' || !data.metadata) {
    throw new Error('The server sent an unexpected response.')
  }
  return data
}
