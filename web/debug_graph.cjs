// 本地复现图谱渲染:headless cytoscape 完整解析样式与元素
const cytoscape = require('./node_modules/cytoscape')

const TYPE_ICON = {
  domain: '<circle cx="12" cy="12" r="3"/><path d="M12 9V4.5"/>',
  product: '<path d="M22 9.5 12 4.5 2 9.5l10 5 10-5Z"/>',
}
function iconUri(type) {
  const paths = TYPE_ICON[type] || TYPE_ICON.domain
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round">${paths}</svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

const style = [
  { selector: 'node', style: {
      label: 'data(label)', 'font-size': 11,
      'background-color': '#64748B', shape: 'ellipse',
      width: 'data(size)', height: 'data(size)',
      'border-width': 2, 'border-color': '#0B1424',
      'text-outline-color': '#0B1424', 'text-outline-width': 1.5, 'text-outline-opacity': 0.85,
  } },
  { selector: 'edge', style: {
      width: 1.6, 'line-color': '#64748B', 'target-arrow-color': '#64748B',
      'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
      label: 'data(label)', 'text-outline-color': '#0B1424', 'text-outline-width': 1,
  } },
  { selector: 'edge[type="runs_in"]', style: { 'line-color': '#FBBF24', 'target-arrow-color': '#FBBF24' } },
]

const elements = [
  { data: { id: 'dom1', label: '学生课程知识域', type: 'domain', status: 'confirmed', size: 58 },
    style: { 'background-color': '#E9C46A', shape: 'ellipse', width: 58, height: 58,
      'border-color': '#F7E7B4', 'border-width': 2.5,
      'background-image': iconUri('domain'), 'background-fit': 'center',
      'background-width': '56%', 'background-height': '56%' } },
  { data: { id: 'e1', label: '北京线下班', type: 'product', status: 'extracted', size: 34 },
    style: { 'background-color': '#5B8DEF', shape: 'ellipse', width: 34, height: 34,
      'background-image': iconUri('product'), 'background-fit': 'center',
      'background-width': '56%', 'background-height': '56%' } },
  { data: { id: 'rel1', source: 'e1', target: 'dom1', label: '归属', origin: 'derived', type: 'belongs_to' },
    style: { 'line-color': '#5B6B81', 'target-arrow-color': '#5B6B81', 'line-style': 'dashed', opacity: 0.62, width: 1.3 } },
]

try {
  const cy = cytoscape({ headless: true, elements, style })
  console.log('OK nodes:', cy.nodes().length, 'edges:', cy.edges().length)
  process.exit(0)
} catch (e) {
  console.error('ERR:', e.message)
  console.error(e.stack.split('\n').slice(0, 8).join('\n'))
  process.exit(1)
}
