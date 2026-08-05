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
  'admin.institution': { zh: '机构信息', en: 'Institution' },
  'admin.agents': { zh: '智能体设置', en: 'Agent Settings' },
  'admin.docs': { zh: '课程资料', en: 'Course Materials' },
  'admin.sessions': { zh: '对话记录', en: 'Conversations' },
  'admin.stats': { zh: '用量统计', en: 'Usage Stats' },
  'admin.subscription': { zh: '套餐订阅', en: 'Subscription' },
  // 平台超管
  'portal.tenants': { zh: '租户管理', en: 'Tenants' },
  'portal.plans': { zh: '套餐定价', en: 'Plans' },
  'portal.orders': { zh: '订单管理', en: 'Orders' },
  'portal.tenantBoard': { zh: '租户看板', en: 'Tenant Board' },
  'portal.system': { zh: '系统设置', en: 'System' },
  // 工作台通用
  'wb.logout': { zh: '退出登录', en: 'Sign Out' },
  'wb.platformOps': { zh: 'AI 教育顾问 · 平台经营', en: 'AI Advisor · Platform Ops' },
  'wb.tenantWs': { zh: 'AI课程顾问管理工作台', en: 'AI Course Advisor Console' },
  'wb.loading': { zh: '加载中…', en: 'Loading…' },
  'wb.freeHint': { zh: '当前为免费版:仅智能体设置可用。升级标准版解锁知识域与课程资料。', en: 'Free plan: only Agent Settings available. Upgrade to unlock knowledge base.' },
  'wb.upgrade': { zh: '去升级 ->', en: 'Upgrade ->' },
  // ---- Tab 标签 ----
  'tab.institution': { zh: '机构信息', en: 'Institution' },
  'tab.institution.d': { zh: '机构名称 · 统一服务宗旨', en: 'Name · Service Purpose' },
  'tab.agents': { zh: '智能体设置', en: 'Agent Settings' },
  'tab.agents.d': { zh: '模型 · 能力 · 知识域 · 提示词', en: 'Model · Caps · Domains · Prompts' },
  'tab.docs': { zh: '知识域', en: 'Knowledge Domains' },
  'tab.docs.d': { zh: '知识域 · 知识库 · 课程资料', en: 'Domains · KBs · Documents' },
  'tab.ontology': { zh: '本体知识', en: 'Ontology' },
  'tab.ontology.d': { zh: '实体 · 规则 · 关系', en: 'Entities · Rules · Relations' },
  'tab.sessions': { zh: '对话记录', en: 'Conversations' },
  'tab.sessions.d': { zh: '脱敏 · 时间筛选 · 质检', en: 'Masked · Filter · QA' },
  'tab.leads': { zh: '线索转化', en: 'Leads' },
  'tab.leads.d': { zh: '报名意向 · 留资工单', en: 'Intent · Work Orders' },
  'tab.analytics': { zh: '运营分析', en: 'Analytics' },
  'tab.analytics.d': { zh: '高频问题 · 未答 · 洞察', en: 'Top Q · Unanswered · Insights' },
  'tab.usage': { zh: '用量统计', en: 'Usage' },
  'tab.usage.d': { zh: '对话次数 · 活跃用户 · 趋势', en: 'Chats · Active · Trend' },
  'tab.sub': { zh: '套餐订阅', en: 'Subscription' },
  'tab.sub.d': { zh: '免费版 / 标准版 / 旗舰版', en: 'Free / Standard / Flagship' },
  'tab.tenants': { zh: '租户管理', en: 'Tenants' },
  'tab.tenants.d': { zh: '机构租户 · 套餐 · 用量概览', en: 'Tenants · Plans · Usage' },
  'tab.plans': { zh: '套餐定价', en: 'Plans' },
  'tab.plans.d': { zh: '标准版 / 旗舰版 · 价格维护', en: 'Standard / Flagship · Pricing' },
  'tab.orders': { zh: '订单管理', en: 'Orders' },
  'tab.orders.d': { zh: '支付流水 · 状态核对', en: 'Payment Flow · Status' },
  'tab.board': { zh: '租户看板', en: 'Dashboard' },
  'tab.board.d': { zh: '租户级对话数 · 用户数 · 趋势图表', en: 'Tenant Chats · Users · Charts' },
  'tab.system': { zh: '系统设置', en: 'System' },
  'tab.system.d': { zh: '模型服务 · API Key · 渠道 · 全局参数', en: 'Model · API Key · Channels' },
  // ---- 锁定面板 ----
  'lock.docs': { zh: '知识域与知识库管理:创建知识域、上传课程资料,是 AI 顾问的知识基础。', en: 'Knowledge domain & document management — the knowledge base for your AI advisor.' },
  'lock.ontology': { zh: '本体知识:班型/营期/费用等实体与规则的图谱化维护。', en: 'Ontology: entities, rules, and relations in graph form.' },
  'lock.sessions': { zh: '对话记录:查看会话明细(脱敏)、按时间筛选、质检评分。', en: 'Conversations: view sessions (masked), filter by date, quality scoring.' },
  'lock.leads': { zh: '线索转化:报名意向工单跟进与状态管理。', en: 'Leads: enrollment intent tracking and status management.' },
  'lock.analytics': { zh: '运营分析:高频问题、未答问题、趋势与 LLM 洞察。', en: 'Analytics: top questions, unanswered, trends, and LLM insights.' },
  'lock.usage': { zh: '用量统计:对话次数、活跃用户与近 14 日趋势图表。', en: 'Usage: chat count, active users, 14-day trend chart.' },
  'lock.needStandard': { zh: '标准版功能', en: 'Standard Feature' },
  'lock.needFlagship': { zh: '旗舰版功能', en: 'Flagship Feature' },
  'lock.unlock': { zh: '升级套餐解锁 ->', en: 'Upgrade to unlock ->' },
  // ---- 能力开关 ----
  'cap.lead_capture': { zh: '留资转线索', en: 'Lead Capture' },
  'cap.lead_capture.d': { zh: '用户表达报名意向时采集联系方式,转线索跟进', en: 'Collect contact info when users show enrollment intent' },
  'cap.quality_check': { zh: '对话质检', en: 'Quality Check' },
  'cap.quality_check.d': { zh: '对该智能体的会话进行质检评分', en: 'Score conversations for this agent' },
  // ---- 通用按钮/状态 ----
  'btn.save': { zh: '保存', en: 'Save' },
  'btn.delete': { zh: '删除', en: 'Delete' },
  'btn.create': { zh: '创建', en: 'Create' },
  'btn.cancel': { zh: '取消', en: 'Cancel' },
  'btn.upload': { zh: '上传并摄入', en: 'Upload & Ingest' },
  'btn.newDomain': { zh: '+ 新建知识域', en: '+ New Domain' },
  'btn.newAgent': { zh: '+ 新建智能体', en: '+ New Agent' },
  'btn.newKb': { zh: '+ 新建知识库', en: '+ New KB' },
  'btn.savePrompt': { zh: '保存提示词', en: 'Save Prompt' },
  'btn.saveWelcome': { zh: '保存欢迎语', en: 'Save Welcome' },
  'btn.copyLink': { zh: '复制链接', en: 'Copy Link' },
  'btn.openNew': { zh: '新窗口打开', en: 'Open' },
  'btn.deleteAgent': { zh: '删除智能体', en: 'Delete Agent' },
  // ---- 线索状态 ----
  'lead.pending': { zh: '待跟进', en: 'Pending' },
  'lead.followed': { zh: '已跟进', en: 'Followed' },
  'lead.converted': { zh: '已转化', en: 'Converted' },
  'lead.invalid': { zh: '无效', en: 'Invalid' },
  // ---- 智能体设置卡片标题 ----
  'agent.frontendLink': { zh: '前台链接(该智能体专属)', en: 'Frontend Link (Agent-specific)' },
  'agent.model': { zh: '推理模型', en: 'Model' },
  'agent.caps': { zh: '能力配置', en: 'Capabilities' },
  'agent.domains': { zh: '知识域对接', en: 'Domain Binding' },
  'agent.prompt': { zh: '系统提示词', en: 'System Prompt' },
  'agent.welcome': { zh: '欢迎语', en: 'Welcome Message' },
  'agent.deleteTitle': { zh: '删除智能体', en: 'Delete Agent' },
  'agent.deleteHint': { zh: '删除后该智能体的前台链接失效,历史会话记录保留。', en: 'The frontend link will be disabled; conversation history is retained.' },
  // ---- 机构信息 ----
  'inst.title': { zh: '机构信息', en: 'Institution Info' },
  'inst.name': { zh: '机构名称(1-40 字)', en: 'Institution Name (1-40 chars)' },
  'inst.purpose': { zh: '统一服务宗旨', en: 'Service Purpose' },
  'inst.purposeHint': { zh: '该机构所有智能体的共同服务导向,置于每个智能体系统提示词顶部,优先级最高;留空则仅使用各智能体自身配置。保存后新会话即时生效。', en: 'Shared service purpose injected at the top of every agent prompt. Leave empty to use individual agent settings.' },
  'inst.save': { zh: '保存设置', en: 'Save' },
  // ---- 用量统计 ----
  'stats.totalChats': { zh: '总对话次数', en: 'Total Chats' },
  'stats.activeUsers': { zh: '活跃用户量(会话)', en: 'Active Users' },
  'stats.used': { zh: '累计对话', en: 'Total Used' },
  'stats.remaining': { zh: '剩余', en: 'Remaining' },
  'stats.unlimited': { zh: '套餐不限次', en: 'Unlimited' },
  'stats.trend14': { zh: '近 14 日会话趋势', en: '14-Day Session Trend' },
  // ---- 对话记录 ----
  'sess.title': { zh: '对话记录(内容已脱敏)', en: 'Conversations (Masked)' },
  'sess.to': { zh: '至', en: 'to' },
  'sess.clear': { zh: '清除', en: 'Clear' },
  'sess.select': { zh: '选择左侧会话查看消息', en: 'Select a session to view messages' },
  'sess.empty': { zh: '该时间范围内暂无对话', en: 'No conversations in this range' },
  'sess.user': { zh: '用户', en: 'User' },
  'sess.advisor': { zh: '顾问', en: 'Advisor' },
  // ---- 套餐订阅 ----
  'sub.current': { zh: '当前订阅', en: 'Current Subscription' },
  'sub.currentPlan': { zh: '当前套餐', en: 'Current' },
  'sub.activate': { zh: '开通', en: 'Activate' },
  'sub.upgrade': { zh: '升级开通', en: 'Upgrade' },
  'sub.orders': { zh: '订单记录', en: 'Order History' },
  'sub.noOrders': { zh: '暂无订单', en: 'No orders yet' },
  // ---- 表头 ----
  'th.doc': { zh: '文档', en: 'Document' },
  'th.status': { zh: '状态', en: 'Status' },
  'th.chunks': { zh: '知识块', en: 'Chunks' },
  'th.entities': { zh: '实体', en: 'Entities' },
  'th.uploaded': { zh: '上传时间', en: 'Uploaded' },
  'th.orderId': { zh: '订单号', en: 'Order ID' },
  'th.plan': { zh: '套餐', en: 'Plan' },
  'th.channel': { zh: '渠道', en: 'Channel' },
  'th.amount': { zh: '金额', en: 'Amount' },
  'th.paidAt': { zh: '支付时间', en: 'Paid At' },
  'th.tenant': { zh: '租户', en: 'Tenant' },
  'th.created': { zh: '开通时间', en: 'Created' },
  'th.users': { zh: '用户', en: 'Users' },
  'th.sessions': { zh: '会话', en: 'Sessions' },
  'th.chats': { zh: '对话数', en: 'Chats' },
  'th.usage': { zh: '累计用量', en: 'Total Usage' },
  'th.price': { zh: '月价(¥)', en: 'Price (¥)' },
  'th.limit': { zh: '对话限额', en: 'Chat Limit' },
  'th.activeSubs': { zh: '开通租户数', en: 'Active Subs' },
  'th.features': { zh: '功能', en: 'Features' },
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
