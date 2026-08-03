/* 支付弹窗:选渠道 → 下单 → 支付 → 轮询确认 → 订阅升级。
   - 模拟支付:点击确认即成功(演示)
   - 微信支付:Native 扫码(code_url → 二维码,2s 轮询订单状态)
   - 支付宝:电脑网站支付(新窗口打开 pay_url,2s 轮询订单状态) */
import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { useI18n } from './i18n'

type Plan = { code: string; name: string; price_monthly: number }
type Channel = { code: string; name: string; configured: boolean }

export default function PaymentModal({ plan, onClose, onDone }: {
  plan: Plan; onClose: () => void; onDone: () => void
}) {
  const { t } = useI18n()
  const [channels, setChannels] = useState<Channel[]>([])
  const [channel, setChannel] = useState('mock')
  const [stage, setStage] = useState<'confirm' | 'paying' | 'success'>('confirm')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [qrUrl, setQrUrl] = useState('')
  const orderIdRef = useRef<number>(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api('/api/billing/channels').then(d => {
      setChannels(d.channels || [])
      const real = (d.channels || []).find((c: Channel) => c.code !== 'mock' && c.configured)
      if (real) setChannel(real.code)
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  function startPolling(orderId: number) {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const r = await api(`/api/billing/orders/${orderId}/status`)
        if (r.status === 'paid') {
          if (pollRef.current) clearInterval(pollRef.current)
          setResult(r)
          setStage('success')
        } else if (r.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          setError('支付未完成或已关闭,请重试')
          setStage('confirm')
        }
      } catch { /* 轮询容错 */ }
    }, 2000)
  }

  async function pay() {
    setError(''); setStage('paying'); setQrUrl('')
    try {
      const o = await api('/api/billing/orders', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_code: plan.code, channel }),
      })
      const order = o.order
      orderIdRef.current = order.id
      if (channel === 'mock') {
        await new Promise(r => setTimeout(r, 700))   // 模拟收银台处理
        const r = await api(`/api/billing/orders/${order.id}/confirm`, { method: 'POST' })
        setResult(r); setStage('success')
        return
      }
      const info = order.pay_info || {}
      if (channel === 'wechat') {
        if (!info.code_url) throw new Error('微信下单未返回二维码')
        setQrUrl(`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(info.code_url)}`)
        startPolling(order.id)
      } else if (channel === 'alipay') {
        if (!info.pay_url) throw new Error('支付宝下单未返回支付链接')
        window.open(info.pay_url, '_blank')
        startPolling(order.id)
      }
    } catch (e: any) {
      setError(e.message?.includes(':') ? e.message.split(':').slice(1).join(':').trim() : (e.message || '支付失败'))
      setStage('confirm')
    }
  }

  return (
    <div className="pm-mask" onClick={stage === 'paying' && channel !== 'mock' ? undefined : onClose}>
      <div className="pm-modal" onClick={e => e.stopPropagation()}>
        {stage === 'confirm' && (<>
          <h3>{t('pay.orderTitle')}</h3>
          <div className="pm-order">
            <div><span>{t('pay.plan')}</span><b>{plan.name}</b></div>
            <div><span>{t('pay.period')}</span><b>{t('pay.oneMonth')}</b></div>
            <div><span>{t('pay.amount')}</span><b className="pm-amount">¥{plan.price_monthly.toFixed(2)}</b></div>
          </div>
          <div className="pm-channels">
            {channels.map(c => (
              <label key={c.code}
                className={`${channel === c.code ? 'on' : ''}${!c.configured && c.code !== 'mock' ? ' disabled' : ''}`}
                title={c.configured ? '' : '渠道未配置(.env 缺少密钥),暂不可用'}>
                <input type="radio" checked={channel === c.code}
                  disabled={!c.configured && c.code !== 'mock'}
                  onChange={() => setChannel(c.code)} />
                <span><b>{c.name}</b>
                  <small>{c.code === 'mock' ? t('pay.mockNote')
                    : c.configured ? '真实支付渠道' : '未配置'}</small></span>
              </label>
            ))}
          </div>
          {error && <div className="auth-error">{error}</div>}
          <div className="pm-actions">
            <button className="pm-cancel" onClick={onClose}>{t('common.cancel')}</button>
            <button className="pm-pay" onClick={pay}>
              {channel === 'mock' ? t('pay.payBtn') : '立即支付'}
            </button>
          </div>
        </>)}

        {stage === 'paying' && (
          channel === 'wechat' ? (
            <div className="pm-paying">
              {qrUrl
                ? <>
                  <img src={qrUrl} alt="微信支付二维码" style={{ width: 200, height: 200, borderRadius: 10 }} />
                  <p>请使用微信扫码支付 ¥{plan.price_monthly.toFixed(2)}</p>
                  <small>支付完成后自动确认(2 秒轮询);也可等待微信回调</small>
                </>
                : <><span className="pm-spinner" /><p>正在生成支付二维码…</p></>}
              <div className="pm-actions" style={{ marginTop: 14 }}>
                <button className="pm-cancel" onClick={onClose}>{t('common.cancel')}</button>
              </div>
            </div>
          ) : channel === 'alipay' ? (
            <div className="pm-paying">
              <span className="pm-spinner" />
              <p>已在新窗口打开支付宝收银台</p>
              <small>完成支付后自动确认;若窗口被拦截,请允许弹窗后重试</small>
              <div className="pm-actions" style={{ marginTop: 14 }}>
                <button className="pm-cancel" onClick={onClose}>{t('common.cancel')}</button>
              </div>
            </div>
          ) : (
            <div className="pm-paying">
              <span className="pm-spinner" />
              <p>{t('pay.paying')}</p>
            </div>
          )
        )}

        {stage === 'success' && (<>
          <div className="pm-success">
            <span className="pm-check">✓</span>
            <h3>{t('pay.success')}</h3>
            <p>已开通「{result?.subscription?.plan_name || plan.name}」,相应功能已解锁。</p>
            <div className="pm-actions">
              <button className="pm-pay" onClick={onDone}>{t('pay.goAdmin')}</button>
            </div>
          </div>
        </>)}
      </div>
    </div>
  )
}
