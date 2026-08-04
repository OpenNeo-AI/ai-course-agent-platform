/* 统一认证面板:横版布局 + 多页签(验证码登录 / 密码登录 / 注册开通)。
   /portal 未登录时内嵌展示;/login 与 /register 以 initialTab 预选页签。
   注册=机构名+手机号+验证码,开通免费版租户;验证码登录仅已注册手机号。 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, saveAuth } from './api'

export type AuthTab = 'sms' | 'password' | 'register'

const PHONE_RE = /^1[3-9]\d{9}$/
const USER_RE = /^[A-Za-z0-9_-]{3,24}$/

export default function AuthPanel({ initialTab = 'sms', onOk, standalone = false }: {
  initialTab?: AuthTab
  onOk?: () => void            // /portal 内嵌:登录成功回调(不再跳转)
  standalone?: boolean         // 独立页(/login /register):登录成功跳转 /portal
}) {
  const nav = useNavigate()
  const [tab, setTab] = useState<AuthTab>(initialTab)
  const [orgName, setOrgName] = useState('')
  const [regUser, setRegUser] = useState('')     // 注册页签:账户名
  const [regPass, setRegPass] = useState('')     // 注册页签:密码
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [username, setUsername] = useState('')   // 密码登录页签:账户名或手机号
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [demoCode, setDemoCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => { if (timer.current) clearInterval(timer.current) }, [])

  function afterAuth(d: any) {
    saveAuth(d.token, {
      username: d.user?.username, role: d.user?.role, tenant_id: d.user?.tenant_id,
      tenant_slug: d.tenant?.slug, tenant_name: d.tenant?.name,
    })
    if (onOk) { onOk(); return }
    nav('/portal')
  }

  async function sendCode() {
    setError(''); setDemoCode('')
    if (!PHONE_RE.test(phone)) { setError('请输入正确的手机号'); return }
    try {
      const res = await fetch(API + '/api/auth/sms/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || '发送失败')
      if (d.demo) setDemoCode(d.code)
      setCountdown(60)
      timer.current = setInterval(() => {
        setCountdown(c => {
          if (c <= 1 && timer.current) clearInterval(timer.current)
          return c - 1
        })
      }, 1000)
    } catch (e: any) { setError(e.message || '发送失败') }
  }

  async function submit() {
    if (busy) return
    setBusy(true); setError('')
    try {
      let path = '/api/auth/login'
      let body: Record<string, string> = {}
      if (tab === 'register') {
        if (!orgName.trim()) throw new Error('请填写机构名称')
        if (!USER_RE.test(regUser.trim())) throw new Error('账户名需为 3-24 位字母/数字/下划线/中划线')
        if (!regPass || regPass.length < 6) throw new Error('密码至少 6 位')
        if (!PHONE_RE.test(phone)) throw new Error('请输入正确的手机号')
        if (!code.trim()) throw new Error('请填写验证码')
        path = '/api/auth/sms/register'
        body = { org_name: orgName, username: regUser.trim(), password: regPass, phone, code }
      } else if (tab === 'sms') {
        if (!PHONE_RE.test(phone)) throw new Error('请输入正确的手机号')
        if (!code.trim()) throw new Error('请填写验证码')
        path = '/api/auth/sms/login'
        body = { phone, code }
      } else {
        if (!username.trim() || !password) throw new Error('请输入账户与密码')
        body = { username: username.trim(), password }
      }
      const res = await fetch(API + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `请求失败(${res.status})`)
      afterAuth(d)
    } catch (e: any) {
      setError(e.message || '操作失败,请重试')
    } finally { setBusy(false) }
  }

  const TABS: { key: AuthTab; label: string }[] = [
    { key: 'sms', label: '验证码登录' },
    { key: 'password', label: '密码登录' },
    { key: 'register', label: '注册开通' },
  ]

  return (
    <div className="aw-page">
      <div className="aw-card">
        <aside className="aw-brand">
          <div className="aw-brand-top">
            <img src="/logo.png" alt="AI 教育顾问" />
            <b>AI 教育顾问 SaaS 平台</b>
          </div>
          <h2>让每家机构<br />都有自己的 AI 课程顾问</h2>
          <ul>
            <li>知识域隔离 · RAG 带引用问答</li>
            <li>课程详情 / 班型推荐 Agent Skill</li>
            <li>免费版体验 · 标准版 / 旗舰版按需升级</li>
          </ul>
          <div className="aw-brand-demo">
            演示账号(密码均 demo1234):<br />
            admin 平台超管 · demo1 旗舰版 · demo2 标准版 · demo3 免费版
          </div>
        </aside>

        <div className="aw-form">
          {standalone && <Link to="/" className="aw-back">← 返回首页</Link>}
          <div className="aw-tabs">
            {TABS.map(t => (
              <button key={t.key} className={tab === t.key ? 'on' : ''}
                onClick={() => { setTab(t.key); setError('') }}>{t.label}</button>
            ))}
          </div>

          {tab === 'register' && (<>
            <label className="aw-field">
              <span>机构名称</span>
              <input value={orgName} onChange={e => setOrgName(e.target.value)}
                placeholder="例如:启明教育培训学校" maxLength={40} />
            </label>
            <label className="aw-field">
              <span>账户名</span>
              <input value={regUser} onChange={e => setRegUser(e.target.value.trim())}
                placeholder="3-24 位字母/数字/下划线,用于密码登录" maxLength={24}
                autoComplete="username" />
            </label>
            <label className="aw-field">
              <span>密码</span>
              <input type="password" value={regPass} onChange={e => setRegPass(e.target.value)}
                placeholder="至少 6 位" autoComplete="new-password" />
            </label>
          </>)}

          {tab !== 'password' ? (<>
            <label className="aw-field">
              <span>手机号</span>
              <input value={phone} onChange={e => setPhone(e.target.value.trim())}
                placeholder={tab === 'register' ? '用于接收验证码与登录' : '注册时的手机号'}
                maxLength={11} />
            </label>
            <label className="aw-field">
              <span>短信验证码</span>
              <div className="aw-code-row">
                <input value={code} onChange={e => setCode(e.target.value.trim())}
                  placeholder="6 位验证码" maxLength={6}
                  onKeyDown={e => e.key === 'Enter' && submit()} />
                <button type="button" className="aw-code-btn" onClick={sendCode}
                  disabled={countdown > 0}>
                  {countdown > 0 ? `${countdown}s 后重发` : '获取验证码'}
                </button>
              </div>
            </label>
            {demoCode && (
              <div className="aw-demo-code">
                演示环境(未接短信网关):本次验证码为 <b>{demoCode}</b>
              </div>
            )}
          </>) : (<>
            <label className="aw-field">
              <span>账户</span>
              <input value={username} onChange={e => setUsername(e.target.value.trim())}
                placeholder="账户名或注册手机号" autoComplete="username" />
            </label>
            <label className="aw-field">
              <span>密码</span>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder="请输入密码" autoComplete="current-password"
                onKeyDown={e => e.key === 'Enter' && submit()} />
            </label>
          </>)}

          {error && <div className="aw-error">{error}</div>}
          <button className="aw-submit" onClick={submit} disabled={busy}>
            {busy ? '处理中…'
              : tab === 'register' ? '注册并开通(免费版)'
                : tab === 'sms' ? '登录' : '登录'}
          </button>
          <p className="aw-hint">
            {tab === 'register'
              ? '账户名+密码用于密码登录,手机号+验证码用于验证码登录;注册即开通免费版'
              : tab === 'sms' ? '未注册的手机号请先切换到「注册开通」页签'
                : '支持账户名或注册手机号登录'}
          </p>
        </div>
      </div>
    </div>
  )
}
