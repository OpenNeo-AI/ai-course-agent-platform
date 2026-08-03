export const API = (import.meta.env.VITE_API_BASE as string | undefined) || ''
export const TOKEN_KEY = 'opc_portal_token'
export const USER_KEY = 'opc_user'   // {username, role, tenant_id, tenant_slug?, tenant_name?}

export function saveAuth(token: string, user: Record<string, unknown>) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function currentUser(): any {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export async function api(path: string, opts: RequestInit = {}): Promise<any> {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  const res = await fetch(API + path, {
    ...opts,
    headers: { ...(opts.headers as Record<string, string> || {}), Authorization: `Bearer ${token}` },
  })
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY)
    throw new Error('401')
  }
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}
