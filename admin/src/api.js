const BASE = '/logs/api'

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...options,
  })
  if (resp.status === 401) {
    window.location.href = '/logs/login'
    throw new Error('Unauthorized')
  }
  return resp.json()
}

export async function getSessions(limit = 200) {
  return request(`/sessions?limit=${limit}`)
}

export async function getSession(id) {
  return request(`/session/${id}`)
}

export async function getUsers() {
  return request('/users')
}

export async function login(email, password) {
  const resp = await fetch(`${BASE}/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return resp.json()
}

export async function logout() {
  await fetch(`${BASE}/logout`, { credentials: 'include' })
  window.location.href = '/logs/login'
}

export async function checkAuth() {
  try {
    const resp = await fetch(`${BASE}/me`, { credentials: 'include' })
    if (resp.status === 401) return null
    return resp.json()
  } catch {
    return null
  }
}
