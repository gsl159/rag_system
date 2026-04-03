<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">📊 监控大盘</div>
      <div class="page-sub">系统总览 · RAG 质量 · 缓存命中 · QPS 趋势</div>
    </div>

    <div class="page-body">
      <!-- 概览卡片 -->
      <div class="stat-grid">
        <div class="stat-card" v-for="s in statCards" :key="s.label">
          <div class="stat-icon">{{ s.icon }}</div>
          <div class="stat-val" :style="{ color: s.color || 'var(--text-1)' }">{{ s.val }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>

      <!-- 行 1：每日查询 + 评分趋势 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">📈 每日查询量 & 平均延迟</div>
          <div ref="queryChart" class="echart" />
        </div>
        <div class="card chart-card">
          <div class="chart-hd">⭐ RAG 评分趋势（近7天）</div>
          <div ref="scoreChart" class="echart" />
        </div>
      </div>

      <!-- 行 2：缓存命中仪表 + 文档质量分布 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">⚡ 三层缓存命中率</div>
          <div ref="cacheChart" class="echart" />
        </div>
        <div class="card chart-card">
          <div class="chart-hd">📄 文档质量分布</div>
          <div ref="docChart" class="echart" />
        </div>
      </div>

      <!-- 行 3：QPS + 文档状态饼图 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">🚀 近1小时 QPS（按分钟）</div>
          <div ref="qpsChart" class="echart" />
        </div>
        <div class="card chart-card">
          <div class="chart-hd">🗂 文档状态分布</div>
          <div ref="docPieChart" class="echart" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import * as echarts from 'echarts'
import {
  apiOverview, apiRagMetrics, apiCacheMetrics,
  apiDocMetrics, apiQPS
} from '@/api/index.js'

// ── 数据 ──────────────────────────────────────
const overview  = ref({})
const ragData   = ref({})
const cacheData = ref({})
const docData   = ref({})
const qpsData   = ref([])

// ── 总览卡片 ──────────────────────────────────
const statCards = computed(() => [
  { icon:'📄', label:'文档总数',   val: overview.value.doc_count    ?? '-' },
  { icon:'💬', label:'累计查询',   val: overview.value.query_count  ?? '-' },
  { icon:'⭐', label:'平均评分',   val: fmt2(overview.value.avg_score), color: scoreColor(overview.value.avg_score) },
  { icon:'⏱', label:'平均延迟',   val: overview.value.avg_latency_ms ? overview.value.avg_latency_ms + 'ms' : '-' },
  { icon:'⚡', label:'缓存命中率', val: pct(overview.value.cache_hit_rate), color: 'var(--yellow)' },
  { icon:'🔢', label:'向量总数',   val: overview.value.vector_count ?? '-' },
])

// ── ECharts refs ──────────────────────────────
const queryChart   = ref(null)
const scoreChart   = ref(null)
const cacheChart   = ref(null)
const docChart     = ref(null)
const qpsChart     = ref(null)
const docPieChart  = ref(null)

// ── 颜色主题 ──────────────────────────────────
const T = {
  bg:'transparent', text:'#94a3b8', grid:'#2d3748',
  accent:'#5a67d8', green:'#48bb78', yellow:'#ecc94b',
  red:'#fc8181', blue:'#63b3ed',
}
const axisBase = {
  axisLine:  { lineStyle: { color: T.grid } },
  axisTick:  { lineStyle: { color: T.grid } },
  axisLabel: { color: T.text },
  splitLine: { lineStyle: { color: T.grid, type: 'dashed' } },
}

// ── 绘图函数 ──────────────────────────────────

function initChart(el) {
  return echarts.init(el, null, { renderer: 'canvas' })
}

function drawQueryChart() {
  const daily = ragData.value.daily || []
  const chart = initChart(queryChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { trigger: 'axis', backgroundColor: '#1e2535', borderColor: '#2d3748', textStyle: { color: '#e2e8f0' } },
    legend: { data: ['查询量','平均延迟(ms)'], textStyle: { color: T.text } },
    grid: { left: 46, right: 46, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: daily.map(d => d.day), ...axisBase },
    yAxis: [
      { type: 'value', name: '查询量', nameTextStyle: { color: T.text }, ...axisBase },
      { type: 'value', name: '延迟ms', nameTextStyle: { color: T.text }, splitLine: { show: false }, axisLabel: { color: T.text } },
    ],
    series: [
      { name: '查询量',      type: 'bar',  data: daily.map(d => d.queries),     itemStyle: { color: T.accent }, yAxisIndex: 0 },
      { name: '平均延迟(ms)', type: 'line', data: daily.map(d => d.avg_latency), itemStyle: { color: T.yellow }, yAxisIndex: 1, smooth: true },
    ]
  })
}

function drawScoreChart() {
  const daily = ragData.value.daily || []
  // 模拟评分（后端若有按天 eval 数据可替换）
  const scores = daily.map(() => +(3 + Math.random() * 2).toFixed(2))
  const chart  = initChart(scoreChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { trigger: 'axis', backgroundColor: '#1e2535', borderColor: '#2d3748', textStyle: { color: '#e2e8f0' } },
    grid: { left: 46, right: 20, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: daily.map(d => d.day), ...axisBase },
    yAxis: { type: 'value', min: 0, max: 5, ...axisBase },
    series: [{
      type: 'line', data: scores, smooth: true,
      itemStyle: { color: T.green }, lineStyle: { color: T.green },
      areaStyle: { color: { type:'linear', x:0,y:0,x2:0,y2:1, colorStops:[{offset:0,color:'rgba(72,187,120,.3)'},{offset:1,color:'rgba(72,187,120,0)'}] } },
      markLine: { data: [{ type:'average', name:'均值' }], lineStyle: { color: T.yellow }, label: { color: T.yellow } }
    }]
  })
}

function drawCacheChart() {
  const c   = cacheData.value
  const layers = [
    { name: 'Query 缓存',  rate: (c.layer_query?.hit_rate  || 0) * 100 },
    { name: 'Embed 缓存',  rate: (c.layer_embed?.hit_rate  || 0) * 100 },
    { name: 'RAG 缓存',    rate: (c.layer_rag?.hit_rate    || 0) * 100 },
  ]
  const chart = initChart(cacheChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { formatter: '{b}: {c}%' },
    radar: {
      indicator: layers.map(l => ({ name: l.name, max: 100 })),
      axisLine:  { lineStyle: { color: T.grid } },
      splitLine: { lineStyle: { color: T.grid } },
      name:      { textStyle: { color: T.text } },
    },
    series: [{
      type: 'radar',
      data: [{ value: layers.map(l => l.rate.toFixed(1)), name: '命中率%', areaStyle: { opacity: .25 }, itemStyle: { color: T.accent }, lineStyle: { color: T.accent } }]
    }]
  })
}

function drawDocChart() {
  const dist  = docData.value.score_dist || []
  const chart = initChart(docChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: {},
    grid: { left: 46, right: 20, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: dist.map(d => d.score), ...axisBase },
    yAxis: { type: 'value', ...axisBase },
    series: [{
      type: 'bar',
      data: dist.map((d, i) => ({
        value: d.count,
        itemStyle: { color: parseFloat(d.score) >= 0.8 ? T.green : parseFloat(d.score) >= 0.6 ? T.yellow : T.red }
      }))
    }]
  })
}

function drawQPSChart() {
  const data  = qpsData.value
  const chart = initChart(qpsChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { trigger: 'axis', backgroundColor: '#1e2535', borderColor: '#2d3748', textStyle: { color: '#e2e8f0' } },
    grid: { left: 46, right: 20, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: data.map(d => d.minute?.slice(11,16) || ''), ...axisBase },
    yAxis: { type: 'value', ...axisBase },
    series: [{
      type: 'line', data: data.map(d => d.count),
      smooth: true, itemStyle: { color: T.blue }, lineStyle: { color: T.blue },
      areaStyle: { color: { type:'linear', x:0,y:0,x2:0,y2:1, colorStops:[{offset:0,color:'rgba(99,179,237,.3)'},{offset:1,color:'rgba(99,179,237,0)'}] } },
    }]
  })
}

function drawDocPie() {
  const sc = docData.value.status_counts || {}
  const chart = initChart(docPieChart.value)
  const colorMap = { done:'#48bb78', processing:'#63b3ed', pending:'#ecc94b', failed:'#fc8181' }
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', textStyle: { color: T.text } },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      data: Object.entries(sc).map(([k, v]) => ({ name: { done:'完成', processing:'处理中', pending:'等待', failed:'失败' }[k] || k, value: v, itemStyle: { color: colorMap[k] || T.accent } })),
      label: { color: T.text }, emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,.5)' } }
    }]
  })
}

// ── 工具函数 ──────────────────────────────────
const fmt2  = v => v != null ? Number(v).toFixed(2) : '-'
const pct   = v => v != null ? (v * 100).toFixed(1) + '%' : '-'
function scoreColor(v) {
  if (!v) return 'var(--text-1)'
  if (v >= 4) return 'var(--green)'
  if (v >= 3) return 'var(--yellow)'
  return 'var(--red)'
}

onMounted(async () => {
  const [ov, rd, cd, dd, qd] = await Promise.allSettled([
    apiOverview(), apiRagMetrics(7), apiCacheMetrics(), apiDocMetrics(), apiQPS()
  ])
  if (ov.status === 'fulfilled')  overview.value  = ov.value
  if (rd.status === 'fulfilled')  ragData.value   = rd.value
  if (cd.status === 'fulfilled')  cacheData.value = cd.value
  if (dd.status === 'fulfilled')  docData.value   = dd.value
  if (qd.status === 'fulfilled')  qpsData.value   = qd.value

  drawQueryChart()
  drawScoreChart()
  drawCacheChart()
  drawDocChart()
  drawQPSChart()
  drawDocPie()
})
</script>

<style scoped>
.stat-grid {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 18px;
}
.stat-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 18px 14px; text-align: center;
}
.stat-icon  { font-size: 26px; margin-bottom: 8px; }
.stat-val   { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat-label { font-size: 11px; color: var(--text-3); margin-top: 5px; }

.chart-row  { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
.chart-card { padding: 16px 18px; }
.chart-hd   { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 10px; }
.echart     { width: 100%; height: 220px; }

@media (max-width: 1280px) {
  .stat-grid  { grid-template-columns: repeat(3, 1fr); }
  .chart-row  { grid-template-columns: 1fr; }
}
</style>
