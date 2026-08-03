/* 套餐页 /pricing:免费版 vs 专业版功能对比 + 支付演示入口。 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, currentUser } from './api'
import PaymentModal from './PaymentModal'
import { LangSwitch, useI18n } from './i18n'

type Plan = { code: string; name: string; price_monthly: number; chat_limit_month: number;
  features: { desc?: string; rag_manage?: boolean; dashboard?: boolean } }

const FEATURE_ROWS: { label: string; free: string | boolean; pro: string | boolean }[] = [
  { label: 'AI 对话次数', free: '50 次 / 月', pro: '无限' },
  { label: 'RAG 知识库问答(带引用)', free: true, pro: true },
  { label: 'Agent Skill(课程详情/班型推荐)', free: true, pro: true },
  { label: '课程资料上传与管理', free: false, pro: true },
  { label: '数据看板(用量图表)', free: false, pro: true },
  { label: '对话记录与质检', free: true, pro: true },
]

function Mark({ v }: { v: string | boolean }) {
  if (typeof v === 'string') return <b className="pm-val">{v}</b>
  return v
    ? <span className="pm-yes" aria-label="支持">✓</span>
    : <span className="pm-no" aria-label="不支持">—</span>
}

export default function Pricing() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [payPlan, setPayPlan] = useState<Plan | null>(null)
  const me = currentUser()
  const nav = useNavigate()
  const { t } = useI18n()

  useEffect(() => {
    fetch(API + '/api/plans').then(r => r.json()).then(d => setPlans(d.plans || [])).catch(() => {})
  }, [])

  function choose(plan: Plan) {
    if (plan.code === 'free') { nav('/register'); return }
    if (!me || me.role === 'superadmin' || !me.tenant_id) { nav('/login'); return }
    setPayPlan(plan)
  }

  return (
    <div className="pricing-page">
      <header className="pricing-top">
        <Link to="/" className="auth-back" style={{ position: 'static' }}>← {t('common.home')}</Link>
        <h1>{t('pricing.title')}</h1>
        <p>{t('pricing.sub')}</p>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 10 }}><LangSwitch /></div>
      </header>

      <div className="pricing-cards">
        {plans.map(p => (
          <div key={p.code} className={`plan-card${p.code === 'pro' ? ' pro' : ''}`}>
            {p.code === 'pro' && <span className="plan-flag">{t('pricing.recommended')}</span>}
            <h2>{p.name}</h2>
            <div className="plan-price">
              <em>¥{p.price_monthly}</em><span>{t('pricing.perMonth')}</span>
            </div>
            <p className="plan-desc">{p.features.desc}</p>
            <button className="plan-cta" onClick={() => choose(p)}>
              {t(p.code === 'free' ? 'pricing.freeCta' : 'pricing.proCta')}
            </button>
          </div>
        ))}
      </div>

      <div className="pricing-table-wrap">
        <h3>{t('pricing.compare')}</h3>
        <table className="pricing-table">
          <thead>
            <tr><th>{t('pricing.feature')}</th><th>免费版 Free</th><th>专业版 Pro</th></tr>
          </thead>
          <tbody>
            {FEATURE_ROWS.map(r => (
              <tr key={r.label}>
                <td>{r.label}</td>
                <td><Mark v={r.free} /></td>
                <td><Mark v={r.pro} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {payPlan && (
        <PaymentModal plan={payPlan} onClose={() => setPayPlan(null)}
          onDone={() => { setPayPlan(null); nav('/admin') }} />
      )}
    </div>
  )
}
