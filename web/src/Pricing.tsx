/* 套餐页 /pricing:免费版 vs 专业版功能对比 + 支付演示入口。 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API, currentUser } from './api'
import PaymentModal from './PaymentModal'
import { LangSwitch, useI18n } from './i18n'

type Plan = { code: string; name: string; price_monthly: number; chat_limit_month: number;
  features: { desc?: string; rag_manage?: boolean; dashboard?: boolean } }

const FEATURE_ROWS: { label: string; std: string | boolean; flag: string | boolean }[] = [
  { label: 'AI 对话次数', std: '不限', flag: '不限' },
  { label: '知识域 / 知识库管理', std: true, flag: true },
  { label: '课程资料上传(PDF 解析 · RAG)', std: true, flag: true },
  { label: 'Agent Skill(课程详情/班型推荐)', std: true, flag: true },
  { label: '本体图谱维护', std: true, flag: true },
  { label: '对话记录(脱敏 · 时间筛选 · 质检)', std: false, flag: true },
  { label: '线索跟进 / 数据分析', std: false, flag: true },
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
    // 两档均为收费套餐:未注册先注册(注册后在工作台开通),已登录租户直接支付
    if (!me || !me.tenant_id) { nav('/register'); return }
    if (me.role === 'superadmin') { nav('/portal'); return }
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
          <div key={p.code} className={`plan-card${p.code === 'flagship' ? ' pro' : ''}`}>
            {p.code === 'flagship' && <span className="plan-flag">{t('pricing.recommended')}</span>}
            <h2>{p.name}</h2>
            <div className="plan-price">
              <em>¥{p.price_monthly}</em><span>{t('pricing.perMonth')}</span>
            </div>
            <p className="plan-desc">{p.features.desc}</p>
            <button className="plan-cta" onClick={() => choose(p)}>
              {me?.tenant_id ? '立即开通' : '注册并开通'}
            </button>
          </div>
        ))}
      </div>

      <div className="pricing-table-wrap">
        <h3>{t('pricing.compare')}</h3>
        <table className="pricing-table">
          <thead>
            <tr><th>{t('pricing.feature')}</th><th>标准版 Standard</th><th>旗舰版 Flagship</th></tr>
          </thead>
          <tbody>
            {FEATURE_ROWS.map(r => (
              <tr key={r.label}>
                <td>{r.label}</td>
                <td><Mark v={r.std} /></td>
                <td><Mark v={r.flag} /></td>
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
