// 高保真复现:线上真实图数据 + 生产样式全量 + fcose 布局
const cytoscape = require('./node_modules/cytoscape')
const fcose = require('./node_modules/cytoscape-fcose')
cytoscape.use(fcose)

const LINK_COLORS = {
  runs_in: '#FBBF24', located_at: '#2DD4BF', teaches: '#A78BFA', has_fee_item: '#FB923C',
  governed_by: '#F472B6', discount_of: '#E9C46A', prerequisite_of: '#F87171',
  variant_of: '#67E8F9', belongs_to: '#5B6B81', sourced_from: '#475569',
}
const DEFAULT_LINK_COLOR = '#64748B'
const TYPE_SIZE = { domain: 58, product: 34, period: 30, location: 28, person: 28, fee_item: 24, rule: 22, document: 22, other: 22 }
const TYPE_COLOR = { domain: '#E9C46A', product: '#5B8DEF', period: '#FBBF24', location: '#2DD4BF', person: '#A78BFA', fee_item: '#FB923C', rule: '#F472B6', document: '#94A3B8', other: '#64748B' }
const TYPE_ICON = {
  domain: '<circle cx="12" cy="12" r="3"/><path d="M12 9V4.5M12 15v4.5M9 12H4.5M15 12h4.5"/><circle cx="12" cy="3.5" r="1.6"/><circle cx="12" cy="20.5" r="1.6"/><circle cx="3.5" cy="12" r="1.6"/><circle cx="20.5" cy="12" r="1.6"/>',
  product: '<path d="M22 9.5 12 4.5 2 9.5l10 5 10-5Z"/><path d="M6 11.8V16c0 1.8 2.7 3.2 6 3.2s6-1.4 6-3.2v-4.2"/><path d="M22 9.5V15"/>',
}
function iconUri(type) {
  const paths = TYPE_ICON[type] || TYPE_ICON.product
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

function buildStyle(schema) {
  const st = [
    { selector: 'node', style: {
        label: 'data(label)', 'font-size': 11, 'font-weight': '500',
        'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 6,
        color: '#DCE6F2', 'text-wrap': 'ellipsis', 'text-max-width': '130px',
        'text-outline-color': '#0B1424', 'text-outline-width': 1.5, 'text-outline-opacity': 0.85,
        'background-color': '#64748B', shape: 'ellipse',
        width: 'data(size)', height: 'data(size)',
        'border-width': 2, 'border-color': '#0B1424', 'overlay-opacity': 0,
    } },
  ]
  for (const [code, t] of Object.entries(schema.object_types || {})) {
    st.push({ selector: `node[type="${code}"]`, style: { 'background-color': t.color, shape: t.shape || 'ellipse' } })
  }
  st.push(
    { selector: 'node[type="domain"]', style: { 'border-width': 2.5, 'border-color': '#F7E7B4' } },
    { selector: 'node[status="confirmed"]', style: { 'border-color': '#E9C46A', 'border-width': 3 } },
    { selector: 'node[status="edited"]', style: { 'border-color': '#7DD3FC', 'border-width': 3 } },
    { selector: 'node.hov', style: { 'border-color': '#E9C46A', 'border-width': 3.5 } },
    { selector: 'node:selected', style: { 'border-color': '#F7E7B4', 'border-width': 5 } },
    { selector: 'edge', style: {
        width: 1.6, 'line-color': DEFAULT_LINK_COLOR, 'target-arrow-color': DEFAULT_LINK_COLOR,
        'target-arrow-shape': 'triangle', 'arrow-scale': 0.95,
        'curve-style': 'bezier', label: 'data(label)', 'font-size': 8.5,
        color: '#9FB0C7', 'text-rotation': 'autorotate', 'text-margin-y': -5,
        'text-outline-color': '#0B1424', 'text-outline-width': 1, 'text-outline-opacity': 0.8,
        'overlay-opacity': 0, opacity: 0.9,
    } },
    { selector: 'edge[origin="derived"]', style: { 'line-style': 'dashed', opacity: 0.62, width: 1.3 } },
    { selector: 'edge[origin="manual"]', style: { width: 2.8, opacity: 1 } },
    { selector: 'edge.hov', style: { width: 3.4, opacity: 1 } },
    { selector: '.faded', style: { opacity: 0.07 } },
    { selector: '.hl', style: { opacity: 1 } },
  )
  for (const [rel, color] of Object.entries(LINK_COLORS)) {
    st.push({ selector: `edge[type="${rel}"]`, style: { 'line-color': color, 'target-arrow-color': color } })
  }
  return st
}

async function main() {
  const TOK = '6kPv6zjyaen6TD80_IvScg'
  const H = { Authorization: `Bearer ${TOK}` }
  const [schema, graph] = await Promise.all([
    fetch('https://edu-demo.openneo.ai/api/portal/ontology/schema', { headers: H }).then(r => r.json()),
    fetch('https://edu-demo.openneo.ai/api/portal/ontology/graph?domain=domain-a', { headers: H }).then(r => r.json()),
  ])
  console.log('fetched: nodes', graph.nodes.length, 'edges', graph.edges.length)

  // 检查空值字段
  for (const n of graph.nodes) {
    for (const k of ['id', 'label', 'type', 'status']) {
      if (n[k] == null) console.log('NULL node field:', k, JSON.stringify(n))
    }
  }
  for (const e of graph.edges) {
    for (const k of ['id', 'source', 'target', 'label', 'origin', 'type']) {
      if (e[k] == null) console.log('NULL edge field:', k, JSON.stringify(e))
    }
  }

  const deg = {}
  for (const e of graph.edges) {
    deg[e.source] = (deg[e.source] || 0) + 1
    deg[e.target] = (deg[e.target] || 0) + 1
  }
  const elements = [
    ...graph.nodes.map(n => {
      const t = schema?.object_types?.[n.type]
      const size = (TYPE_SIZE[n.type] ?? 22) + Math.min((deg[n.id] || 0) * 2.5, 20)
      const st = {
        'background-color': t?.color || TYPE_COLOR[n.type] || '#64748B',
        shape: 'ellipse', width: size, height: size,
        'border-color': '#0B1424', 'border-width': 2,
        'background-image': iconUri(n.type),
        'background-fit': 'center', 'background-width': '56%', 'background-height': '56%',
      }
      if (n.type === 'domain') Object.assign(st, { 'border-color': '#F7E7B4', 'border-width': 2.5 })
      if (n.status === 'confirmed') Object.assign(st, { 'border-color': '#E9C46A', 'border-width': 3 })
      else if (n.status === 'edited') Object.assign(st, { 'border-color': '#7DD3FC', 'border-width': 3 })
      return { data: { id: n.id, label: n.label, type: n.type, status: n.status, size }, style: st }
    }),
    ...graph.edges.map(e => {
      const c = LINK_COLORS[e.type] || DEFAULT_LINK_COLOR
      const st = { 'line-color': c, 'target-arrow-color': c }
      if (e.origin === 'derived') Object.assign(st, { 'line-style': 'dashed', opacity: 0.62, width: 1.3 })
      if (e.origin === 'manual') Object.assign(st, { width: 2.8, opacity: 1 })
      return { data: { id: e.id, source: e.source, target: e.target, label: e.label, origin: e.origin, type: e.type }, style: st }
    }),
  ]

  try {
    const cy = cytoscape({ headless: true, elements, style: buildStyle(schema) })
    console.log('create OK:', cy.nodes().length, 'nodes')
    cy.layout({ name: 'fcose', animate: false, fit: true, padding: 40,
      nodeRepulsion: 7500, idealEdgeLength: 100, edgeElasticity: 0.4,
      gravity: 0.25, gravityRange: 1.5, numIter: 2200, tile: true, quality: 'default' }).run()
    console.log('fcose OK')
    cy.batch(() => {
      cy.nodes().forEach(n => n.style('display', 'element'))
    })
    console.log('visibility OK')
    // 模拟选中邻域
    const first = cy.nodes()[0]
    cy.elements().addClass('faded')
    first.closedNeighborhood().removeClass('faded').addClass('hl')
    console.log('highlight OK')
    process.exit(0)
  } catch (e) {
    console.error('CRASH:', e.message)
    console.error(e.stack.split('\n').slice(0, 10).join('\n'))
    process.exit(1)
  }
}

main().catch(e => { console.error('fetch/other:', e.message); process.exit(1) })
