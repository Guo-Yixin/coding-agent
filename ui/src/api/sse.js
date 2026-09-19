function parseBlock(block) {
  const dataLines = []
  let eventName = 'message'

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }

  if (!dataLines.length) return null
  const payload = JSON.parse(dataLines.join('\n'))

  if (payload && typeof payload === 'object' && payload.event) {
    return {
      event: payload.event,
      data: payload.data || {},
    }
  }

  return {
    event: eventName,
    data: payload || {},
  }
}

export async function streamAgentMessage(threadId, payload, { signal, onEvent }) {
  const url = threadId
    ? `/dashboard/api/threads/${encodeURIComponent(threadId)}/stream-message`
    : '/dashboard/api/threads/stream-message'

  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `SSE 请求失败：HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const parsed = parseBlock(block)
      if (parsed) onEvent(parsed.event, parsed.data)
    }

    if (done) break
  }

  if (buffer.trim()) {
    const parsed = parseBlock(buffer)
    if (parsed) onEvent(parsed.event, parsed.data)
  }
}
