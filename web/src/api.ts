export const API = (import.meta.env.VITE_API_BASE as string | undefined) || ''
export const TOKEN_KEY = 'opc_portal_token'

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
