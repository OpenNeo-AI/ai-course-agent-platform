import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from './i18n'
import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { api } from './api'

cytoscape.use(fcose)

/* 链接类型配色:每类关系独立色相,网络语义一目了然 */
const LINK_COLORS: Record<string, string> = {
  runs_in: '#B39A5E',
  located_at: '#7FA698',
  teaches: '#9A8DB4',
  has_fee_item: '#B48D6C',
  governed_by: '#AE8C9D',
  discount_of: '#C2A468',
  prerequisite_of: '#B28A8A',
  variant_of: '#7DA3B0',
  belongs_to: '#57647D',
  sourced_from: '#4A576E',
}
const DEFAULT_LINK_COLOR = '#5A6B84'

/* 深色画布配色兜底(schema 缺失时)——与 schema 同一套雅致低饱和色 */
const TYPE_COLOR: Record<string, string> = {
  domain: '#D9B46F', product: '#8AA5CE', period: '#C7A876', location: '#8AB3A6',
  person: '#A79BC2', fee_item: '#C69A78', rule: '#BC93A4', document: '#8E9DB2', other: '#6E7D93',
}

/* 类型图标:24×24 线条示意图,白色线条置于彩色圆内(知识域金底用墨色) */
const TYPE_ICON: Record<string, string> = {
  // 知识域:中心枢纽 + 四向辐条
  domain: '<circle cx="12" cy="12" r="3"/><path d="M12 9V4.5M12 15v4.5M9 12H4.5M15 12h4.5"/><circle cx="12" cy="3.5" r="1.6"/><circle cx="12" cy="20.5" r="1.6"/><circle cx="3.5" cy="12" r="1.6"/><circle cx="20.5" cy="12" r="1.6"/>',
  // 班型/产品:学位帽
  product: '<path d="M22 9.5 12 4.5 2 9.5l10 5 10-5Z"/><path d="M6 11.8V16c0 1.8 2.7 3.2 6 3.2s6-1.4 6-3.2v-4.2"/><path d="M22 9.5V15"/>',
  // 营期:日历
  period: '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M8 2.5V7M16 2.5V7M3.5 10.5h17"/><path d="M8 14.5h3M8 17.5h6"/>',
  // 教学地点:地图钉
  location: '<path d="M19.5 10c0 5.5-7.5 11.5-7.5 11.5S4.5 15.5 4.5 10a7.5 7.5 0 0 1 15 0Z"/><circle cx="12" cy="10" r="3"/>',
  // 师资:人形
  person: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-3.8 3.3-6 7.5-6s7.5 2.2 7.5 6"/>',
  // 费用项:¥ 圆币
  fee_item: '<circle cx="12" cy="12" r="9"/><path d="M8.5 7.5l3.5 4.5 3.5-4.5M12 12v5M9.3 13.6h5.4M9.3 15.8h5.4"/>',
  // 业务规则:天平
  rule: '<path d="M12 3.5v17M7.5 20.5h9M4 7.5h3c2 0 3.5-.8 5-2 1.5 1.2 3 2 5 2h3"/><path d="m2.5 14 3.5-6.5L9.5 14c-1 .75-2.2 1.15-3.5 1.15S3.5 14.75 2.5 14Z"/><path d="m14.5 14 3.5-6.5L21.5 14c-1 .75-2.2 1.15-3.5 1.15s-2.5-.4-3.5-1.15Z"/>',
  // 知识文档:文件页
  document: '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8Z"/><path d="M14 2.5V8h5.5"/><path d="M15.5 13h-7M15.5 16.5h-7"/>',
  // 其他:星芒
  other: '<path d="M12 3.5l1.7 4.8 4.8 1.7-4.8 1.7L12 16.5l-1.7-4.8-4.8-1.7 4.8-1.7Z"/><path d="M18.5 15.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9Z"/>',
}

/* 图标以 DOM SVG 覆盖层渲染(不经 cytoscape canvas 图像通道,规避图像缓存崩溃) */

const LAYOUTS = [
  { key: 'fcose', label: '力导向' },
  { key: 'radial', label: '放射' },
  { key: 'cluster', label: '聚簇' },
  { key: 'concentric', label: '同心圆' },
  { key: 'breadthfirst', label: '层级' },
  { key: 'circle', label: '环形' },
  { key: 'grid', label: '网格' },
]

/* 放射布局:最高度数节点为圆心,BFS 分层成环;同环节点按已定位邻居的角度均值排序减少交叉 */
function radialPositions(cy: any): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {}
  const ns = cy.nodes(':visible')
  if (!ns.length) return pos
  const remaining = new Set(ns.map((n: any) => n.id()))
  const angleOf = new Map<string, number>()
  let ringOffset = 0

  while (remaining.size) {
    const startId = remaining.values().next().value as string
    const compDist = new Map<string, number>()
    let frontier: string[] = [startId]
    compDist.set(startId, 0)
    remaining.delete(startId)
    let d = 0
    const levels: string[][] = [[startId]]
    while (frontier.length) {
      const next: string[] = []
      for (const id of frontier) {
        cy.getElementById(id).neighborhood('node:visible').forEach((m: any) => {
          if (!compDist.has(m.id())) {
            compDist.set(m.id(), d + 1)
            remaining.delete(m.id())
            next.push(m.id())
          }
        })
      }
      d++
      if (next.length) levels.push(next)
      frontier = next
    }
    // 按环放置
    levels.forEach((ids, li) => {
      const ring = ringOffset + li
      // 同环按已定位邻居角度均值排序(减少边交叉)
      if (li > 0) {
        ids.sort((a, b) => baryAngle(a) - baryAngle(b))
      }
      ids.forEach((id, i) => {
        const r = ring === 0 ? 0 : ring * 92
        const angle = ids.length === 1 && ring === 0 ? 0
          : (i / ids.length) * 2 * Math.PI - Math.PI / 2 + (ring % 2 ? Math.PI / ids.length : 0)
        pos[id] = { x: Math.cos(angle) * r, y: Math.sin(angle) * r }
        angleOf.set(id, angle)
      })
    })
    ringOffset += levels.length + 1   // 下一连通分量跳过一环,避免重叠
  }

  function baryAngle(id: string): number {
    let sum = 0, cnt = 0
    cy.getElementById(id).neighborhood('node:visible').forEach((m: any) => {
      if (angleOf.has(m.id())) { sum += angleOf.get(m.id())!; cnt++ }
    })
    return cnt ? sum / cnt : 999
  }
  return pos
}

/* 聚簇布局:按对象类型分簇,簇心分布在大环上,成员环绕簇心小环排列 */
function clusterPositions(cy: any): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {}
  const groups = new Map<string, any[]>()
  cy.nodes(':visible').forEach((n: any) => {
    const t = n.data('type') || 'other'
    if (!groups.has(t)) groups.set(t, [])
    groups.get(t)!.push(n)
  })
  const entries = [...groups.entries()].sort((a, b) => b[1].length - a[1].length)
  const R = entries.length > 1 ? 225 : 0
  entries.forEach(([, members], gi) => {
    const a = entries.length === 1 ? 0 : (gi / entries.length) * 2 * Math.PI - Math.PI / 2
    const cx = Math.cos(a) * R
    const cyy = Math.sin(a) * R
    if (members.length === 1) {
      pos[members[0].id()] = { x: cx, y: cyy }
      return
    }
    const r = 28 + Math.sqrt(members.length) * 21
    members.forEach((n, i) => {
      const ma = (i / members.length) * 2 * Math.PI - Math.PI / 2
      pos[n.id()] = { x: cx + Math.cos(ma) * r, y: cyy + Math.sin(ma) * r }
    })
  })
  return pos
}

function buildStyle(schema: any) {
  const st: any[] = [
    { selector: 'node', style: {
        label: 'data(label)', 'font-size': 10.5, 'font-weight': '500',
        'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 5,
        color: '#DCE6F2', 'text-wrap': 'ellipsis', 'text-max-width': '118px',
        'text-outline-color': '#0B1424', 'text-outline-width': 1.5, 'text-outline-opacity': 0.85,
        'background-color': '#64748B', shape: 'ellipse',
        width: 'data(size)', height: 'data(size)',
        'border-width': 1.5, 'border-color': '#0B1424',
        'overlay-opacity': 0,
    } },
  ]
  for (const [code, t] of Object.entries<any>(schema.object_types || {})) {
    st.push({ selector: `node[type="${code}"]`,
      style: { 'background-color': t.color, shape: t.shape || 'ellipse' } })
  }
  st.push(
    // 知识域:金色圆,域名置于节点下方(节点统一小尺寸,名字不入内)
    { selector: 'node[type="domain"]', style: {
        'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 5,
        color: '#F7E7B4', 'font-size': 11, 'font-weight': '700',
        'text-outline-color': '#0B1424', 'text-outline-width': 1.5, 'text-outline-opacity': 0.85,
        'text-max-width': '118px',
        'border-width': 2, 'border-color': '#F7E7B4',
    } },
    { selector: 'node[type="product"]', style: { 'font-size': 11, 'font-weight': '700' } },
    { selector: 'node[status="confirmed"]', style: { 'border-color': '#E9C46A', 'border-width': 1.8 } },
    { selector: 'node[status="edited"]', style: { 'border-color': '#7DD3FC', 'border-width': 1.8 } },
    // 悬停金环 + 选中双环(SVG 渲染器下以 border 表达,稳定可见)
    { selector: 'node.hov', style: { 'border-color': '#E9C46A', 'border-width': 2.2 } },
    { selector: 'node:selected', style: { 'border-color': '#F7E7B4', 'border-width': 2.8 } },
    // 边:每类链接独立颜色(在 buildStyle 外按 type 注入),派生虚线、人工加粗
    { selector: 'edge', style: {
        width: 1.1, 'line-color': DEFAULT_LINK_COLOR, 'target-arrow-color': DEFAULT_LINK_COLOR,
        'target-arrow-shape': 'triangle', 'arrow-scale': 0.82,
        'curve-style': 'bezier', label: 'data(label)', 'font-size': 8,
        color: '#8FA0B8', 'text-rotation': 'autorotate', 'text-margin-y': -5,
        'text-outline-color': '#0B1424', 'text-outline-width': 1, 'text-outline-opacity': 0.8,
        'overlay-opacity': 0, opacity: 0.75,
    } },
    { selector: 'edge[origin="derived"]', style: { 'line-style': 'dashed', opacity: 0.5, width: 0.9 } },
    { selector: 'edge[origin="manual"]', style: { width: 1.9, opacity: 0.95 } },
    { selector: 'edge.hov', style: { width: 2.2, opacity: 1 } },
    { selector: '.faded', style: { opacity: 0.07 } },
    { selector: '.hl', style: { opacity: 1 } },
  )
  // 链接类型着色
  for (const [rel, color] of Object.entries(LINK_COLORS)) {
    st.push({ selector: `edge[type="${rel}"]`,
      style: { 'line-color': color, 'target-arrow-color': color } })
  }
  return st
}

function runLayout(cy: any, name: string) {
  const base: any = { fit: true, padding: 40, animate: true,
    animationDuration: 480, animationEasing: 'ease-out' }
  let opt: any
  switch (name) {
    case 'fcose':
      opt = { ...base, name: 'fcose', animate: 'end', nodeRepulsion: 3000, idealEdgeLength: 58,
        edgeElasticity: 0.4, gravity: 0.30, gravityRange: 1.5, numIter: 2200,
        tile: true, quality: 'default' }
      break
    case 'radial':
      opt = { ...base, name: 'preset', positions: radialPositions(cy), padding: 60 }
      break
    case 'cluster':
      opt = { ...base, name: 'preset', positions: clusterPositions(cy), padding: 60 }
      break
    case 'concentric':
      opt = { ...base, name: 'concentric', minNodeSpacing: 52,
        concentric: (n: any) => ({ domain: 12, product: 8, period: 6, rule: 4 } as any)[n.data('type')] ?? 2,
        levelWidth: () => 1 }
      break
    case 'breadthfirst':
      opt = { ...base, name: 'breadthfirst', directed: true, spacingFactor: 1.08 }
      break
    case 'circle':
      opt = { ...base, name: 'circle' }
      break
    default:
      opt = { ...base, name: 'grid' }
  }
  try { cy.layout(opt).run() } catch { cy.layout({ name: 'circle', fit: true }).run() }
}

function applyVisibility(cy: any, visible: Record<string, boolean>) {
  cy.batch(() => {
    cy.nodes().forEach((n: any) =>
      n.style('display', visible[n.data('type')] !== false ? 'element' : 'none'))
    cy.edges().forEach((e: any) =>
      e.style('display', e.source().visible() && e.target().visible() ? 'element' : 'none'))
  })
}

export default function OntologyTab() {
  const { t } = useI18n()
  const [schema, setSchema] = useState<any>(null)
  const [domains, setDomains] = useState<any[]>([])
  const [domain, setDomain] = useState('')
  const [graph, setGraph] = useState<any>(null)
  const [visible, setVisible] = useState<Record<string, boolean>>({})
  const [layout, setLayout] = useState('fcose')
  const [q, setQ] = useState('')
  const [, setSel] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [actions, setActions] = useState<any[]>([])
  const [editText, setEditText] = useState('')
  const [editing, setEditing] = useState(false)
  const [linkForm, setLinkForm] = useState({ rel: '', dst: '' })
  const [msg, setMsg] = useState('')
  const [cyError, setCyError] = useState('')
  const cyBox = useRef<HTMLDivElement>(null)
  const cyRef = useRef<any>(null)
  const iconLayerRef = useRef<HTMLDivElement>(null)

  // 把 DOM SVG 图标对齐到各节点渲染坐标(平移/缩放/布局后调用)
  const updateIconPositions = useCallback(() => {
    const cy = cyRef.current
    const layer = iconLayerRef.current
    if (!cy || !layer || !graph) return
    const icons = layer.children
    graph.nodes.forEach((n: any, i: number) => {
      const el = icons[i] as HTMLElement | undefined
      if (!el) return
      const node = cy.getElementById(n.id)
      if (!node || !node.length || !node.visible()) { el.style.display = 'none'; return }
      el.style.display = ''
      const p = node.renderedPosition()
      const w = node.renderedWidth() * 0.62
      el.style.transform = `translate(${p.x - w / 2}px, ${p.y - w / 2}px)`
      el.style.width = `${w}px`
      el.style.height = `${w}px`
      el.style.opacity = node.hasClass('faded') ? '0.08' : '1'
    })
  }, [graph])

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(''), 3500) }

  useEffect(() => {
    Promise.all([api('/api/portal/ontology/schema'), api('/api/portal/domains')])
      .then(([sc, doms]) => {
        setSchema(sc)
        setDomains(doms)
        setDomain(d => d || doms[0]?.code || '')
        const vis: Record<string, boolean> = { other: true }
        Object.keys(sc.object_types || {}).forEach(t => { vis[t] = true })
        setVisible(vis)
      }).catch(alert)
  }, [])

  const loadGraph = useCallback(async () => {
    if (!domain) return
    try {
      const g = await api(`/api/portal/ontology/graph?domain=${domain}`)
      setGraph(g)
      setSel(null); setDetail(null)
    } catch (e: any) { alert('图谱加载失败:' + e.message) }
  }, [domain])
  useEffect(() => { loadGraph() }, [loadGraph])

  useEffect(() => {
    api('/api/portal/actions?limit=12').then(setActions).catch(() => {})
  }, [graph, detail])

  const selectNode = useCallback(async (id: string) => {
    setSel(id)
    try {
      const d = await api(`/api/portal/ontology/objects/${id}`)
      setDetail(d)
      setEditText(JSON.stringify(d.props ?? {}, null, 2))
      setEditing(false)
    } catch (e: any) { flash('对象详情加载失败') }
    const cy = cyRef.current
    if (cy) {
      cy.elements().removeClass('faded hl')
      const n = cy.getElementById(id)
      if (n && n.length) {
        cy.elements().addClass('faded')
        n.closedNeighborhood().removeClass('faded').addClass('hl')
      }
    }
  }, [])

  // 图谱渲染
  useEffect(() => {
    if (!cyBox.current || !graph || !schema) return
    // 逐元素内联样式:颜色/形状直接落到元素上,不依赖选择器匹配
    const elements = [
      ...graph.nodes.map((n: any) => {
        const t = schema?.object_types?.[n.type]
        const size = 17                // 所有圆形统一尺寸(类型仅以颜色 + 图标区分)
        const st: any = {
          'background-color': t?.color || TYPE_COLOR[n.type] || '#64748B',
          shape: 'ellipse',            // 统一正圆,图标由 DOM 覆盖层渲染
          width: size, height: size,
          'border-color': '#0B1424', 'border-width': 1.1,
        }
        if (n.type === 'domain') Object.assign(st, { 'border-color': '#F7E7B4', 'border-width': 1.5 })
        if (n.status === 'confirmed') Object.assign(st, { 'border-color': '#E9C46A', 'border-width': 1.5 })
        else if (n.status === 'edited') Object.assign(st, { 'border-color': '#7DD3FC', 'border-width': 1.5 })
        return { data: { id: n.id, label: n.label, type: n.type, status: n.status, size }, style: st }
      }),
      ...graph.edges.map((e: any) => {
        const c = LINK_COLORS[e.type] || DEFAULT_LINK_COLOR
        const st: any = { 'line-color': c, 'target-arrow-color': c }
        if (e.origin === 'derived') Object.assign(st, { 'line-style': 'dashed', opacity: 0.62, width: 1.3 })
        if (e.origin === 'manual') Object.assign(st, { width: 2.8, opacity: 1 })
        return { data: { id: e.id, source: e.source, target: e.target, label: e.label, origin: e.origin, type: e.type }, style: st }
      }),
    ]
    if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null }
    let cy: any
    try {
      cy = cytoscape({
        container: cyBox.current, elements, stylesheet: buildStyle(schema),
        wheelSensitivity: 0.18, minZoom: 0.15, maxZoom: 2.6,
      })
    } catch (e: any) {
      console.error('graph render failed', e)
      setCyError(String(e?.message || e))
      return
    }
    setCyError('')
    cyRef.current = cy
    cy.on('tap', 'node', (evt: any) => { void selectNode(evt.target.id()) })
    cy.on('mouseover', 'node', (evt: any) => evt.target.addClass('hov'))
    cy.on('mouseout', 'node', (evt: any) => evt.target.removeClass('hov'))
    cy.on('mouseover', 'edge', (evt: any) => evt.target.addClass('hov'))
    cy.on('mouseout', 'edge', (evt: any) => evt.target.removeClass('hov'))
    cy.on('tap', (evt: any) => {
      if (evt.target === cy) {
        setSel(null); setDetail(null)
        cy.elements().removeClass('faded hl')
      }
    })
    runLayout(cy, layout)
    applyVisibility(cy, visible)
    cy.on('pan zoom resize layoutstop position', () => updateIconPositions())
    requestAnimationFrame(() => updateIconPositions())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, schema])

  useEffect(() => {
    const onResize = () => { cyRef.current?.resize(); updateIconPositions() }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [updateIconPositions])

  const zoomBy = (f: number) => {
    const cy = cyRef.current
    if (!cy) return
    cy.zoom({ level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
  }
  const fitAll = () => cyRef.current?.fit(undefined, 44)

  useEffect(() => {
    if (!cyRef.current) return
    runLayout(cyRef.current, layout)
    requestAnimationFrame(() => updateIconPositions())
  }, [layout, updateIconPositions])
  useEffect(() => {
    if (!cyRef.current) return
    applyVisibility(cyRef.current, visible)
    updateIconPositions()
  }, [visible, updateIconPositions])

  function searchNode() {
    const cy = cyRef.current
    if (!cy || !q.trim()) return
    const ql = q.trim().toLowerCase()
    const found = cy.nodes().filter((n: any) =>
      (n.data('label') || '').toString().toLowerCase().includes(ql))
    if (found.length) {
      const t = found[0]
      cy.center(t)
      cy.animate({ zoom: 1.5, center: { eles: t }, duration: 350 })
      void selectNode(t.id())
    } else { flash('未找到匹配对象') }
  }

  function focusNode(id: string) {
    const cy = cyRef.current
    if (!cy) return
    const n = cy.getElementById(id)
    if (n && n.length) {
      cy.center(n)
      cy.animate({ zoom: 1.5, center: { eles: n }, duration: 350 })
    }
    void selectNode(id)
  }

  async function saveProps() {
    if (!detail) return
    try {
      const obj = JSON.parse(editText)
      if (detail.type === 'rule') {
        const params = { ...obj }
        delete params.kind
        await api(`/api/portal/rules/${detail.id.slice(1)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ params }),
        })
      } else {
        await api(`/api/portal/entities/${detail.id.slice(1)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ attrs: obj }),
        })
      }
      setEditing(false)
      flash('已保存')
      void loadGraph()
      void selectNode(detail.id)
    } catch (e: any) { alert('保存失败(JSON 格式?):' + e.message) }
  }

  async function doConfirm() {
    if (!detail) return
    await api(`/api/portal/entities/${detail.id.slice(1)}/confirm`, { method: 'POST' })
    flash(t('ont.confirmed'))
    void loadGraph()
    void selectNode(detail.id)
  }

  async function addLink() {
    if (!detail || !linkForm.rel || !linkForm.dst) return alert('请选择链接类型与目标对象')
    try {
      await api('/api/portal/ontology/links', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ src_node: detail.id, rel: linkForm.rel, dst_node: linkForm.dst }),
      })
      setLinkForm({ rel: '', dst: '' })
      flash('链接已创建')
      void loadGraph()
      void selectNode(detail.id)
    } catch (e: any) { alert('创建失败:' + e.message) }
  }

  async function removeLink(edgeId: string) {
    if (!confirm('删除该链接?')) return
    await api(`/api/portal/ontology/links/${edgeId}`, { method: 'DELETE' })
    flash('链接已删除')
    void loadGraph()
    if (detail) void selectNode(detail.id)
  }

  async function rederive() {
    if (!confirm('按本体 Schema 重算全部派生链接?')) return
    const r = await api('/api/portal/ontology/derive', { method: 'POST' })
    flash('派生链接已重算:' + JSON.stringify(r.counts))
    void loadGraph()
  }

  const typeLabel = (t: string) => schema?.object_types?.[t]?.label || t
  const stats = graph?.stats || {}
  const linkTypes = Object.entries<any>(schema?.link_types || {})
  const targetOptions = (graph?.nodes || []).filter((n: any) =>
    !linkForm.rel || (schema?.link_types?.[linkForm.rel]?.target || []).includes(n.type))

  return (
    <div>
      <div className="p-card o-toolbar-card">
        <div className="p-toolbar" style={{ marginBottom: 8 }}>
          <select value={domain} onChange={e => setDomain(e.target.value)}>
            {domains.map(d => <option key={d.code} value={d.code}>{d.name}</option>)}
          </select>
          <input placeholder={t('ont.search')} value={q} onChange={e => setQ(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && searchNode()} style={{ width: 180 }} />
          <button onClick={searchNode}>{t('ont.locate')}</button>
          <select value={layout} onChange={e => setLayout(e.target.value)}>
            {LAYOUTS.map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>
          <button onClick={rederive}>{t('ont.rederive')}</button>
          <span className="o-stats">
            {t('ont.objects')} {stats.node_count ?? 0} · {t('ont.links')} {stats.edge_count ?? 0} · {t('ont.confirmed')} {stats.confirmed ?? 0}
            {msg && <span className="p-ok" style={{ marginLeft: 10 }}>{msg}</span>}
          </span>
        </div>
        <div className="o-legend">
          {Object.entries<any>(schema?.object_types || {})
            .filter(([code]) => code !== 'domain' && code !== 'document')
            .map(([code, t]) => (
              <button key={code} className={visible[code] === false ? 'off' : ''}
                onClick={() => setVisible(v => ({ ...v, [code]: v[code] === false }))}>
                <span className="o-legend-ic" style={{ background: t.color }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke={code === 'domain' ? '#1A1305' : '#fff'}
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                    dangerouslySetInnerHTML={{ __html: TYPE_ICON[code] || TYPE_ICON.other }} />
                </span>
                {t.label}
                <span className="o-legend-n">{stats.by_type?.[code] ?? 0}</span>
              </button>
            ))}
          <button className={visible['other'] === false ? 'off' : ''}
            onClick={() => setVisible(v => ({ ...v, other: v['other'] === false }))}>
            <i style={{ background: '#94A3B8' }} />其他{stats.by_type?.['other'] ? ` ${stats.by_type['other']}` : ''}
          </button>
          {([['runs_in', t('link.runs_in')], ['prerequisite_of', t('link.prerequisite_of')], ['discount_of', t('link.discount_of')],
            ['variant_of', t('link.variant_of')], ['located_at', t('link.located_at')], ['teaches', t('link.teaches')]] as const)
            .map(([rel, lab]) => (
              <span key={rel} className="o-legend-edge">
                <i style={{ borderTopColor: LINK_COLORS[rel] }} />{lab}
              </span>
            ))}
          <span className="o-legend-edge"><i className="dashed" /> {t('ont.derivedDashed')}</span>
          <span className="o-legend-edge"><i className="thick" style={{ borderTopColor: '#E9C46A' }} /> {t('ont.manualBold')}</span>
        </div>
      </div>

      <div className="o-wrap">
        <div className="o-main">
          <div className="o-graphwrap">
            <div className="o-graphbox" ref={cyBox} />
            <div className="o-icons" ref={iconLayerRef} aria-hidden="true">
              {(graph?.nodes || []).map((n: any) => (
                <span key={n.id} className="o-icon">
                  <svg viewBox="0 0 24 24" fill="none"
                    stroke={n.type === 'domain' ? '#1A1305' : '#FFFFFF'}
                    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
                    dangerouslySetInnerHTML={{ __html: TYPE_ICON[n.type] || TYPE_ICON.other }} />
                </span>
              ))}
            </div>
            {cyError && (
              <div className="o-grapherror">
                <b>图谱渲染失败</b>
                <p>{cyError}</p>
                <button onClick={() => loadGraph()}>重试</button>
              </div>
            )}
            <div className="o-zoom">
              <button onClick={() => zoomBy(1.35)} aria-label="放大">+</button>
              <button onClick={() => zoomBy(1 / 1.35)} aria-label="缩小">−</button>
              <button onClick={fitAll} aria-label="适应画布">⤢</button>
            </div>
            <div className="o-watermark">Ontology Graph</div>
          </div>
        </div>

        <aside className="o-side">
          {detail
            ? (
              <div className="o-detail">
                <div className="o-detail-head">
                  <span className="p-mat o-typechip" style={{
                    background: schema?.object_types?.[detail.type]?.color || TYPE_COLOR[detail.type] || '#64748B',
                    color: detail.type === 'domain' ? '#1A1305' : '#fff', borderColor: 'transparent',
                  }}>
                    <svg viewBox="0 0 24 24" fill="none" stroke={detail.type === 'domain' ? '#1A1305' : '#fff'}
                      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                      dangerouslySetInnerHTML={{ __html: TYPE_ICON[detail.type] || TYPE_ICON.other }} />
                    {typeLabel(detail.type)}
                  </span>
                  <b>{detail.label}</b>
                  <span className={`p-status ${detail.status}`}>{detail.status}</span>
                </div>
                {(detail.domain_name || detail.chapter || detail.doc) && (
                  <div className="o-detail-meta">
                    {detail.domain_name && <span>知识域:{detail.domain_name}</span>}
                    {detail.chapter && <span>章节:{detail.chapter}</span>}
                    {detail.doc && <span>文档:{detail.doc}</span>}
                  </div>
                )}

                <h3>{t('ont.properties')}</h3>
                {editing
                  ? <>
                      <textarea className="p-scope-editor" rows={10} value={editText}
                        onChange={e => setEditText(e.target.value)} />
                      <div className="p-toolbar" style={{ marginTop: 8 }}>
                        <button onClick={saveProps}>保存</button>
                        <button onClick={() => setEditing(false)}
                          style={{ background: 'transparent', color: 'var(--mut)', border: '1px solid var(--line)' }}>取消</button>
                      </div>
                    </>
                  : <>
                      <table className="o-props">
                        <tbody>
                          {Object.entries(detail.props ?? {}).map(([k, v]) => (
                            <tr key={k}>
                              <td>{schema?.object_types?.[detail.type]?.properties?.[k] || k}</td>
                              <td>{typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className="p-toolbar" style={{ marginTop: 10 }}>
                        <button onClick={() => setEditing(true)}>{t('ont.editProps')}</button>
                        {detail.type !== 'rule' && detail.type !== 'document' && detail.type !== 'domain'
                          && detail.status !== 'confirmed'
                          && <button onClick={doConfirm}>{t('ont.confirmObj')}</button>}
                      </div>
                    </>}

                <h3>链接({detail.links?.length ?? 0})</h3>
                <div className="o-links">
                  {(detail.links || []).map((l: any) => (
                    <div key={l.edge_id} className="o-linkrow">
                      <span className="o-linkdir">{l.direction === 'out' ? '→' : '←'}</span>
                      <span className="o-linkrel">{l.rel_label}</span>
                      <a onClick={() => focusNode(l.other.id)}>{l.other.label}</a>
                      <span className="o-linkorigin">{l.origin === 'manual' ? '人工' : l.origin === 'derived' ? t('ont.derived') : t('ont.extracted')}</span>
                      <span className="del" onClick={() => removeLink(l.edge_id)} title="删除链接">×</span>
                    </div>
                  ))}
                  {!(detail.links || []).length && <div className="o-empty">暂无链接</div>}
                </div>

                <h3>{t('ont.addLink')}</h3>
                <div className="o-addlink">
                  <select value={linkForm.rel}
                    onChange={e => setLinkForm(f => ({ ...f, rel: e.target.value, dst: '' }))}>
                    <option value="">{t('ont.selectLinkType')}</option>
                    {linkTypes.filter(([, lt]) => (lt.source || []).includes(detail.type))
                      .map(([code, lt]) => (
                        <option key={code} value={code}>{lt.label}({code})</option>
                      ))}
                  </select>
                  <select value={linkForm.dst}
                    onChange={e => setLinkForm(f => ({ ...f, dst: e.target.value }))}>
                    <option value="">{t('ont.selectTarget')}</option>
                    {targetOptions.map((n: any) => (
                      <option key={n.id} value={n.id}>{n.label} · {typeLabel(n.type)}</option>
                    ))}
                  </select>
                  <button onClick={addLink}
                    disabled={!linkForm.rel || !linkForm.dst}>{t('ont.createLink')}</button>
                </div>
              </div>
            )
            : (
              <div className="o-detail o-placeholder">
                <b>{t('ont.graphHint')}</b>
                <p>{t('ont.graphHint2')}</p>
              </div>
            )}

          <div className="o-detail">
            <h3 style={{ marginTop: 0 }}>{t('ont.actions')}</h3>
            <div className="o-feed">
              {actions.map(a => (
                <div key={a.id}>
                  <b>{a.action}</b> {a.target}
                  <span>{a.created_at}</span>
                </div>
              ))}
              {!actions.length && <div className="o-empty">{t('ont.noActions')}</div>}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
