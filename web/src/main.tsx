import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import Chat from './Chat'
import Portal from './Portal'
import './index.css'

/* 落地页右侧:循环播放的对话演示 */
const SCRIPT: { role: 'user' | 'assistant'; text: string }[] = [
  { role: 'user', text: '孩子在北京,8月1日到7日有空,想线下参加,推荐哪个班?' },
  { role: 'assistant', text: '推荐「北京线下班 · 第一期」(8月1日—7日):地点与日期均匹配,30人班、满15人开班。' },
  { role: 'user', text: '三个人一起报,7月10日前缴费多少钱?' },
  { role: 'assistant', text: '早鸟价 5,980 元/人(标准 6,980 元 − 早鸟 1,000 元,高于团报 300 元),三人共 17,940 元。' },
]

function LiveDemo() {
  const [step, setStep] = useState(0)   // 已出现的消息数
  const [typing, setTyping] = useState(false)

  useEffect(() => {
    let t: ReturnType<typeof setTimeout>
    if (step >= SCRIPT.length) {
      t = setTimeout(() => { setStep(0); setTyping(false) }, 4600)
    } else {
      setTyping(true)
      t = setTimeout(() => { setTyping(false); setStep(s => s + 1) }, step === 0 ? 1400 : 2200)
    }
    return () => clearTimeout(t)
  }, [step])

  return (
    <div className="l-demo">
      <div className="l-demo-card">
        <div className="l-demo-head">
          <span className="dot" />
          <b>学生通道 · 实时演示</b>
          <span>LIVE</span>
        </div>
        <div className="l-demo-msgs">
          {SCRIPT.slice(0, step).map((m, i) => (
            <div key={i} className={`row ${m.role}`}>
              <div className="bubble">{m.text}</div>
            </div>
          ))}
          {typing && step < SCRIPT.length && (
            <div className={`row ${SCRIPT[step].role}`}>
              <div className="bubble">
                <span className="l-demo-typing"><i /><i /><i /></span>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="l-demo-chip">多路检索 · 本体规则引擎 · 带引用回答</div>
    </div>
  )
}

const ArrowIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14" /><path d="m13 6 6 6-6 6" />
  </svg>
)

function Landing() {
  return (
    <div className="landing">
      <div className="landing-mark" aria-hidden="true">問</div>

      <header className="l-topbar reveal d1">
        <div className="l-brand">
          <img className="l-logo" src="/logo.png" alt="AI 课程顾问" />
          <b>AI 课程顾问</b>
        </div>
        <a href="/intro.html" className="l-intro-link">
          产品介绍
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M7 17L17 7M17 7H9m8 0v8" />
          </svg>
        </a>
        <span className="l-badge">AI 教育中心 · 课程咨询服务</span>
      </header>

      <main className="l-body">
        <section>
          <p className="l-kicker reveal d1">Course Advisor Agent</p>
          <h1 className="l-title reveal d2">问得清楚,<br />答得<em>有据</em>。</h1>
          <p className="l-sub reveal d3">
            基于知识库多路检索与结构化规则引擎的课程咨询服务——班型推荐逐条对应你的约束,
            费用计算确定性拆解,每一条回答都标注出处章节。
          </p>

          <nav className="l-entries" aria-label="咨询入口">
            <Link className="l-entry reveal d3" to="/s">
              <span className="num">01</span>
              <span className="t"><b>学生 / 家长</b><small>暑期AI素养夏令营 · 班型推荐 · 费用与准备事项</small></span>
              <span className="arrow"><ArrowIcon /></span>
            </Link>
            <Link className="l-entry reveal d4" to="/t">
              <span className="num">02</span>
              <span className="t"><b>教师</b><small>L1—L3 AI素养培训 · 集训班 / 周末研修班 · 报名与前置</small></span>
              <span className="arrow"><ArrowIcon /></span>
            </Link>
            <Link className="l-entry reveal d5" to="/c">
              <span className="num">03</span>
              <span className="t"><b>机构 / 企业</b><small>平台服务与会员体系 · 机构合作咨询</small></span>
              <span className="arrow"><ArrowIcon /></span>
            </Link>
          </nav>

          <div className="l-portal-trigger reveal d5">
            <Link to="/portal" className="l-portal-link">
              <span className="l-portal-icon" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
                </svg>
              </span>
              <span className="l-portal-body">
                <b>管理工作台</b>
                <small>知识域管理 · 本体图谱 · 质检分析 · 工单跟进</small>
              </span>
              <span className="l-portal-arrow"><ArrowIcon /></span>
            </Link>
          </div>
        </section>

        <LiveDemo />
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/s" element={<Chat role="student" title="学生通道 · 夏令营咨询" accent="#2563eb"
          suggestions={['8月1日到7日有空,在北京,推荐哪个班?', '北京线下班多少钱?', '上课时间是怎么安排的?', '需要带什么?']} />} />
        <Route path="/t" element={<Chat role="teacher" title="教师通道 · 培训咨询" accent="#059669"
          suggestions={['L2暑期集训班什么时候开课?', '我能连续脱岗,推荐什么培训?', '周末研修班怎么安排?', 'L3需要什么前置条件?']} />} />
        <Route path="/c" element={<Chat role="platform" title="平台通道 · 机构/企业咨询" accent="#7c3aed"
          suggestions={['平台会员有哪些权益?', '机构批量采购如何合作?', '平台提供哪些服务?']} />} />
        <Route path="/portal" element={<Portal />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
