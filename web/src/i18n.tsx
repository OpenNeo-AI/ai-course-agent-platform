/* 轻量多语言:zh/en 静态字典 + Context + localStorage 持久化。
   覆盖 SaaS 相关页面与公共导航的静态文案;AI 回复保持其原语言,不做机翻。 */
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

export type Lang = 'zh' | 'en'

const DICT: Record<string, { zh: string; en: string }> = {
  // 通用
  'common.home': { zh: '返回首页', en: 'Back to Home' },
  'common.login': { zh: '登录', en: 'Sign In' },
  'common.register': { zh: '注册开通', en: 'Sign Up' },
  'common.logout': { zh: '退出登录', en: 'Sign Out' },
  'common.pricing': { zh: '机构套餐', en: 'Pricing' },
  'common.loading': { zh: '加载中…', en: 'Loading…' },
  'common.confirm': { zh: '确认', en: 'Confirm' },
  'common.cancel': { zh: '取消', en: 'Cancel' },
  // 落地页
  'landing.badge': { zh: 'AI 教育中心 · 课程咨询服务', en: 'AI Education Center · Course Advisory' },
  'landing.intro': { zh: '产品介绍', en: 'Product Intro' },
  'landing.saas': { zh: 'SaaS 平台:机构可注册开通专属 AI 课程顾问', en: 'SaaS Platform: institutions can register their own AI course advisor' },
  // 登录/注册
  'auth.loginTitle': { zh: '登录', en: 'Sign In' },
  'auth.registerTitle': { zh: '开通机构账号', en: 'Create Organization Account' },
  'auth.registerSub': { zh: '注册即建专属知识库与 Bot 入口,选购套餐(标准版/旗舰版)后即可启用', en: 'Register to get your own knowledge base & bot; choose a plan to activate' },
  'auth.loginSub': { zh: '机构管理员或平台管理员登录', en: 'For organization or platform administrators' },
  'auth.orgName': { zh: '机构名称', en: 'Organization Name' },
  'auth.username': { zh: '用户名', en: 'Username' },
  'auth.password': { zh: '密码', en: 'Password' },
  'auth.submitLogin': { zh: '登录', en: 'Sign In' },
  'auth.submitRegister': { zh: '注册并开通', en: 'Register & Activate' },
  'auth.hasAccount': { zh: '已有账号?', en: 'Have an account?' },
  'auth.noAccount': { zh: '还没有账号?', en: 'No account yet?' },
  // 套餐页
  'pricing.title': { zh: '选择适合机构的套餐', en: 'Choose the right plan' },
  'pricing.sub': { zh: '演示环境定价 · 支付为模拟流程,不产生真实扣款', en: 'Demo pricing · payments are simulated, no real charges' },
  'pricing.compare': { zh: '功能对比', en: 'Feature Comparison' },
  'pricing.feature': { zh: '功能', en: 'Feature' },
  'pricing.freeCta': { zh: '免费注册开通', en: 'Start Free' },
  'pricing.proCta': { zh: '升级专业版', en: 'Upgrade to Pro' },
  'pricing.recommended': { zh: '推荐', en: 'Recommended' },
  'pricing.perMonth': { zh: '/月', en: '/mo' },
  // 支付弹窗
  'pay.orderTitle': { zh: '确认订单', en: 'Confirm Order' },
  'pay.plan': { zh: '套餐', en: 'Plan' },
  'pay.period': { zh: '订阅周期', en: 'Period' },
  'pay.oneMonth': { zh: '1 个月', en: '1 month' },
  'pay.amount': { zh: '应付金额', en: 'Amount Due' },
  'pay.mock': { zh: '模拟支付', en: 'Mock Payment' },
  'pay.mockNote': { zh: '演示环境 · 点击即支付成功', en: 'Demo · succeeds on click' },
  'pay.real': { zh: '支付宝 / 微信支付', en: 'Alipay / WeChat Pay' },
  'pay.realNote': { zh: '沙箱接入预留', en: 'Sandbox integration reserved' },
  'pay.payBtn': { zh: '确认支付(演示)', en: 'Pay Now (Demo)' },
  'pay.paying': { zh: '正在处理支付请求…', en: 'Processing payment…' },
  'pay.success': { zh: '支付成功', en: 'Payment Successful' },
  'pay.goAdmin': { zh: '进入管理后台', en: 'Go to Admin Console' },
  // 对话页配额
  'chat.quotaLeft': { zh: '剩余', en: 'remaining' },
  'chat.quotaTimes': { zh: '次', en: '' },
  'chat.unlimited': { zh: '不限次', en: 'Unlimited' },
  'chat.quotaBanner': { zh: '免费版对话额度已用完,升级标准版/旗舰版享不限次对话。', en: 'Free chat quota used up. Upgrade to Standard/Flagship for unlimited chats.' },
  'chat.viewPlans': { zh: '查看套餐 →', en: 'View Plans →' },
  // 租户后台
  'admin.docs': { zh: '课程资料', en: 'Course Materials' },
  'admin.sessions': { zh: '对话记录', en: 'Conversations' },
  'admin.stats': { zh: '用量统计', en: 'Usage Stats' },
  'admin.subscription': { zh: '套餐订阅', en: 'Subscription' },
  // 平台工作台
  'portal.tenantBoard': { zh: '租户看板', en: 'Tenant Board' },
}

const I18nCtx = createContext<{ lang: Lang; t: (k: string) => string; setLang: (l: Lang) => void }>({
  lang: 'zh', t: k => DICT[k]?.zh ?? k, setLang: () => {},
})

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    () => (localStorage.getItem('opc_lang') === 'en' ? 'en' : 'zh'))
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem('opc_lang', l)
    setLangState(l)
    document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
  }, [])
  const t = useCallback((k: string) => DICT[k]?.[lang] ?? DICT[k]?.zh ?? k, [lang])
  return <I18nCtx.Provider value={{ lang, t, setLang }}>{children}</I18nCtx.Provider>
}

export function useI18n() {
  return useContext(I18nCtx)
}

/* 语言切换按钮(中英) */
export function LangSwitch() {
  const { lang, setLang } = useI18n()
  return (
    <button className="lang-switch" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
      aria-label="Switch language">
      <span className={lang === 'zh' ? 'on' : ''}>中</span>
      <span className={lang === 'en' ? 'on' : ''}>EN</span>
    </button>
  )
}
