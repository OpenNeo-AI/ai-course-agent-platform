/* 支付演示弹窗:选套餐 → 创建订单 → 模拟支付成功 → 订阅升级 → 功能解锁。
   渠道:内置模拟支付;支付宝/微信沙箱为预留位(CHANNELS 注册表挂接后自动出现)。 */
import { useState } from 'react'
import { api } from './api'

type Plan = { code: string; name: string; price_monthly: number }

export default function PaymentModal({ plan, onClose, onDone }: {
  plan: Plan; onClose: () => void; onDone: () => void
}) {
  const [stage, setStage] = useState<'confirm' | 'paying' | 'success'>('confirm')
  const [channel, setChannel] = useState('mock')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  async function pay() {
    setError('')
    setStage('paying')
    try {
      const o = await api('/api/billing/orders', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_code: plan.code, channel }),
      })
      // 演示环境:模拟收银台处理延时,随后回调确认支付成功
      await new Promise(r => setTimeout(r, 900))
      const r = await api(`/api/billing/orders/${o.order.id}/confirm`, { method: 'POST' })
      setResult(r)
      setStage('success')
    } catch (e: any) {
      setError(e.message?.includes(':') ? e.message.split(':').slice(1).join(':').trim() : (e.message || '支付失败'))
      setStage('confirm')
    }
  }

  return (
    <div className="pm-mask" onClick={stage === 'paying' ? undefined : onClose}>
      <div className="pm-modal" onClick={e => e.stopPropagation()}>
        {stage === 'confirm' && (<>
          <h3>确认订单</h3>
          <div className="pm-order">
            <div><span>套餐</span><b>{plan.name}</b></div>
            <div><span>订阅周期</span><b>1 个月</b></div>
            <div><span>应付金额</span><b className="pm-amount">¥{plan.price_monthly.toFixed(2)}</b></div>
          </div>
          <div className="pm-channels">
            <label className={channel === 'mock' ? 'on' : ''}>
              <input type="radio" checked={channel === 'mock'} onChange={() => setChannel('mock')} />
              <span><b>模拟支付</b><small>演示环境 · 点击即支付成功</small></span>
            </label>
            <label className="disabled" title="真实渠道沙箱挂接中">
              <input type="radio" disabled />
              <span><b>支付宝 / 微信支付</b><small>沙箱接入预留</small></span>
            </label>
          </div>
          {error && <div className="auth-error">{error}</div>}
          <div className="pm-actions">
            <button className="pm-cancel" onClick={onClose}>取消</button>
            <button className="pm-pay" onClick={pay}>确认支付(演示)</button>
          </div>
        </>)}

        {stage === 'paying' && (
          <div className="pm-paying">
            <span className="pm-spinner" />
            <p>正在处理支付请求…</p>
            <small>模拟支付渠道回调中,请稍候</small>
          </div>
        )}

        {stage === 'success' && (<>
          <div className="pm-success">
            <span className="pm-check">✓</span>
            <h3>支付成功</h3>
            <p>已升级「{result?.subscription?.plan_name || plan.name}」,无限对话与知识库管理已解锁。</p>
            <div className="pm-actions">
              <button className="pm-pay" onClick={onDone}>进入管理后台</button>
            </div>
          </div>
        </>)}
      </div>
    </div>
  )
}
