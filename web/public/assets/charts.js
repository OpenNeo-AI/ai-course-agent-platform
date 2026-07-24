(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Chart: Radar (核心能力技术维度评估) ---
  var radarEl = document.getElementById('chart-radar');
  if (radarEl) {
    var chart = echarts.init(radarEl, null, { renderer: 'svg' });
    chart.setOption({
      animation: false,
      tooltip: {
        trigger: 'item',
        appendToBody: true,
        backgroundColor: bg2,
        borderColor: rule,
        borderWidth: 1,
        textStyle: { color: ink, fontSize: 13 }
      },
      legend: {
        bottom: 10,
        textStyle: { color: muted, fontSize: 13 },
        itemWidth: 16,
        itemHeight: 10,
        data: ['知识本体建模', '多路混合检索', '确定性规则引擎', '多智能体隔离', '多渠道交付', '配置即文件']
      },
      radar: {
        indicator: [
          { name: '知识建模深度', max: 100 },
          { name: '检索精度', max: 100 },
          { name: '计算确定性', max: 100 },
          { name: '隔离强度', max: 100 },
          { name: '开放性', max: 100 },
          { name: '可维护性', max: 100 }
        ],
        center: ['50%', '48%'],
        radius: '62%',
        axisName: {
          color: ink,
          fontSize: 13,
          fontWeight: 600
        },
        splitLine: {
          lineStyle: { color: rule, width: 1 }
        },
        splitArea: {
          areaStyle: {
            color: ['rgba(79,70,229,0.02)', 'rgba(79,70,229,0.04)', 'rgba(79,70,229,0.06)', 'rgba(79,70,229,0.08)', 'rgba(79,70,229,0.10)']
          }
        },
        axisLine: {
          lineStyle: { color: rule, width: 1 }
        }
      },
      series: [{
        type: 'radar',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 },
        data: [
          {
            value: [95, 88, 100, 92, 90, 96],
            name: '知识本体建模',
            itemStyle: { color: accent },
            lineStyle: { color: accent, width: 2 },
            areaStyle: { color: 'rgba(79,70,229,0.08)' }
          },
          {
            value: [82, 92, 70, 85, 78, 88],
            name: '多路混合检索',
            itemStyle: { color: accent2 },
            lineStyle: { color: accent2, width: 2 },
            areaStyle: { color: 'rgba(13,148,136,0.06)' }
          },
          {
            value: [78, 75, 98, 80, 72, 90],
            name: '确定性规则引擎',
            itemStyle: { color: '#D97706' },
            lineStyle: { color: '#D97706', width: 2 },
            areaStyle: { color: 'rgba(217,119,6,0.05)' }
          },
          {
            value: [70, 72, 65, 96, 82, 85],
            name: '多智能体隔离',
            itemStyle: { color: '#8B5CF6' },
            lineStyle: { color: '#8B5CF6', width: 2 },
            areaStyle: { color: 'rgba(139,92,246,0.05)' }
          },
          {
            value: [65, 78, 60, 75, 95, 82],
            name: '多渠道交付',
            itemStyle: { color: '#0EA5E9' },
            lineStyle: { color: '#0EA5E9', width: 2 },
            areaStyle: { color: 'rgba(14,165,233,0.05)' }
          },
          {
            value: [85, 80, 72, 88, 76, 94],
            name: '配置即文件',
            itemStyle: { color: '#EC4899' },
            lineStyle: { color: '#EC4899', width: 2 },
            areaStyle: { color: 'rgba(236,72,153,0.05)' }
          }
        ]
      }]
    });
    window.addEventListener('resize', function() { chart.resize(); });
  }
})();
