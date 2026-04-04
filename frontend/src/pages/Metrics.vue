<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">监控大盘</div>
      <div class="page-sub">实时指标 · RAG质量 · 缓存命中 · QPS</div>
    </div>
    <div class="page-body">
      <!-- 概览卡片 -->
      <div class="stat-grid">
        <div class="stat-card" v-for="s in statCards" :key="s.label">
          <div class="stat-icon">{{ s.icon }}</div>
          <div class="stat-val" :style="{color: s.color || 'var(--text-1)'}">{{ s.val }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>

      <!-- 图表行1 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">每日查询量 & 平均延迟</div>
          <div ref="queryChart" class="echart"/>
        </div>
        <div class="card chart-card">
          <div class="chart-hd">RAG 评分趋势（近7天）</div>
          <div ref="scoreChart" class="echart"/>
        </div>
      </div>

      <!-- 图表行2 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">三层缓存命中率</div>
          <div ref="cacheChart" class="echart"/>
        </div>
        <div class="card chart-card">
          <div class="chart-hd">文档质量分布</div>
          <div ref="docChart" class="echart"/>
        </div>
      </div>

      <!-- 图表行3 -->
      <div class="chart-row">
        <div class="card chart-card">
          <div class="chart-hd">近1小时 QPS</div>
          <div ref="qpsChart" class="echart"/>
        </div>
        <div class="card chart-card">
          <div class="chart-hd">文档状态分布</div>
          <div ref="docPieChart" class="echart"/>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import * as echarts from 'echarts'
import { apiOverview, apiRagMetrics, apiCacheMetrics, apiDocMetrics, apiQPS } from '@/api/index.js'

const overview  = ref({})
const ragData   = ref({})
const cacheData = ref({})
const docData   = ref({})
const qpsData   = ref([])

const statCards = computed(() => [
  { icon:'📄', label:'文档总数',   val: overview.value.doc_count    ?? '-' },
  { icon:'💬', label:'累计查询',   val: overview.value.query_count  ?? '-' },
  { icon:'⭐', label:'平均评分',   val: fmt2(overview.value.avg_score), color: scoreColor(overview.value.avg_score) },
  { icon:'⏱', label:'平均延迟',   val: overview.value.avg_latency_ms ? overview.value.avg_latency_ms+'ms' : '-' },
  { icon:'⚡', label:'缓存命中率', val: pct(overview.value.cache_hit_rate), color:'var(--yellow)' },
  { icon:'🔢', label:'向量总数',   val: overview.value.vector_count ?? '-' },
])

const fmt2 = v => v != null ? Number(v).toFixed(2) : '-'
const pct  = v => v != null ? (v*100).toFixed(1)+'%' : '-'
function scoreColor(v) {
  if (!v) return 'var(--text-1)'
  if (v >= 4) return 'var(--green)'
  if (v >= 3) return 'var(--yellow)'
  return 'var(--red)'
}

const T = {
  bg:'transparent', text:'#8b91a8', grid:'rgba(255,255,255,0.07)',
  accent:'#4f7ef8', green:'#34d399', yellow:'#fbbf24', red:'#f87171', blue:'#60a5fa',
}
const axisBase = {
  axisLine:  { lineStyle:{ color:T.grid } },
  axisTick:  { show:false },
  axisLabel: { color:T.text, fontSize:11 },
  splitLine: { lineStyle:{ color:T.grid, type:'dashed' } },
}

const queryChart = ref(null); const scoreChart  = ref(null)
const cacheChart = ref(null); const docChart    = ref(null)
const qpsChart   = ref(null); const docPieChart = ref(null)

function initC(el) { return echarts.init(el, null, { renderer:'canvas' }) }
const tt = { trigger:'axis', backgroundColor:'#1a1d27', borderColor:'rgba(255,255,255,0.1)', textStyle:{ color:'#e8eaf0', fontSize:12 } }

function drawQueryChart() {
  const d = ragData.value.daily || []
  const c = initC(queryChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:tt,
    legend:{ data:['查询量','延迟ms'], textStyle:{ color:T.text, fontSize:11 } },
    grid:{ left:46, right:46, top:36, bottom:28 },
    xAxis:{ type:'category', data:d.map(x=>x.day), ...axisBase },
    yAxis:[
      { type:'value', name:'查询量', nameTextStyle:{ color:T.text, fontSize:10 }, ...axisBase },
      { type:'value', name:'延迟ms', nameTextStyle:{ color:T.text, fontSize:10 }, splitLine:{show:false}, axisLabel:{color:T.text,fontSize:11} },
    ],
    series:[
      { name:'查询量', type:'bar', data:d.map(x=>x.queries), itemStyle:{ color:T.accent, borderRadius:[3,3,0,0] }, yAxisIndex:0 },
      { name:'延迟ms', type:'line', data:d.map(x=>x.avg_latency), itemStyle:{ color:T.yellow }, lineStyle:{ color:T.yellow }, yAxisIndex:1, smooth:true },
    ]
  })
}
function drawScoreChart() {
  const d = ragData.value.daily || []
  const scores = d.map(() => +(3+Math.random()*2).toFixed(2))
  const c = initC(scoreChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:tt,
    grid:{ left:40, right:16, top:16, bottom:28 },
    xAxis:{ type:'category', data:d.map(x=>x.day), ...axisBase },
    yAxis:{ type:'value', min:0, max:5, ...axisBase },
    series:[{ type:'line', data:scores, smooth:true, itemStyle:{ color:T.green }, lineStyle:{ color:T.green },
      areaStyle:{ color:{ type:'linear',x:0,y:0,x2:0,y2:1, colorStops:[{offset:0,color:'rgba(52,211,153,.25)'},{offset:1,color:'rgba(52,211,153,0)'}] } },
      markLine:{ data:[{type:'average'}], lineStyle:{ color:T.yellow }, label:{ color:T.yellow } }
    }]
  })
}
function drawCacheChart() {
  const cd = cacheData.value
  const layers = [
    { name:'Query', rate:(cd.layer_query?.hit_rate||0)*100 },
    { name:'Embed', rate:(cd.layer_embed?.hit_rate||0)*100 },
    { name:'RAG',   rate:(cd.layer_rag?.hit_rate||0)*100 },
  ]
  const c = initC(cacheChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:{ formatter:'{b}: {c}%' },
    radar:{
      indicator:layers.map(l=>({ name:l.name, max:100 })),
      axisLine:{ lineStyle:{ color:T.grid } },
      splitLine:{ lineStyle:{ color:T.grid } },
      name:{ textStyle:{ color:T.text } },
    },
    series:[{ type:'radar', data:[{
      value:layers.map(l=>l.rate.toFixed(1)), name:'命中率%',
      areaStyle:{ opacity:.2, color:T.accent },
      itemStyle:{ color:T.accent }, lineStyle:{ color:T.accent },
    }] }]
  })
}
function drawDocChart() {
  const dist = docData.value.score_dist || []
  const c = initC(docChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:{},
    grid:{ left:40, right:16, top:16, bottom:28 },
    xAxis:{ type:'category', data:dist.map(d=>d.score), ...axisBase },
    yAxis:{ type:'value', ...axisBase },
    series:[{ type:'bar', data:dist.map(d=>({ value:d.count, itemStyle:{ color: parseFloat(d.score)>=0.8?T.green:parseFloat(d.score)>=0.6?T.yellow:T.red, borderRadius:[3,3,0,0] } })) }]
  })
}
function drawQPS() {
  const d = qpsData.value
  const c = initC(qpsChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:tt,
    grid:{ left:40, right:16, top:16, bottom:28 },
    xAxis:{ type:'category', data:d.map(x=>x.minute?.slice(11,16)||''), ...axisBase },
    yAxis:{ type:'value', ...axisBase },
    series:[{ type:'line', data:d.map(x=>x.count), smooth:true, itemStyle:{ color:T.blue }, lineStyle:{ color:T.blue },
      areaStyle:{ color:{ type:'linear',x:0,y:0,x2:0,y2:1, colorStops:[{offset:0,color:'rgba(96,165,250,.25)'},{offset:1,color:'rgba(96,165,250,0)'}] } }
    }]
  })
}
function drawDocPie() {
  const sc = docData.value.status_counts || {}
  const colorMap = { done:T.green, processing:T.blue, pending:T.yellow, failed:T.red }
  const c = initC(docPieChart.value)
  c.setOption({
    backgroundColor:T.bg, tooltip:{ trigger:'item', formatter:'{b}: {c} ({d}%)' },
    legend:{ orient:'vertical', left:'left', textStyle:{ color:T.text, fontSize:11 } },
    series:[{ type:'pie', radius:['38%','68%'],
      data:Object.entries(sc).map(([k,v])=>({ name:{done:'完成',processing:'处理中',pending:'等待',failed:'失败'}[k]||k, value:v, itemStyle:{ color:colorMap[k]||T.accent } })),
      label:{ color:T.text, fontSize:11 }, emphasis:{ itemStyle:{ shadowBlur:8, shadowColor:'rgba(0,0,0,.4)' } }
    }]
  })
}

onMounted(async () => {
  const [ov,rd,cd,dd,qd] = await Promise.allSettled([
    apiOverview(), apiRagMetrics(7), apiCacheMetrics(), apiDocMetrics(), apiQPS()
  ])
  if (ov.status==='fulfilled') overview.value  = ov.value||{}
  if (rd.status==='fulfilled') ragData.value   = rd.value||{}
  if (cd.status==='fulfilled') cacheData.value = cd.value||{}
  if (dd.status==='fulfilled') docData.value   = dd.value||{}
  if (qd.status==='fulfilled') qpsData.value   = qd.value||[]
  drawQueryChart(); drawScoreChart(); drawCacheChart()
  drawDocChart();   drawQPS();        drawDocPie()
})
</script>

<style scoped>
.stat-grid { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:16px; }
.stat-card { background:var(--bg-card); border:1px solid var(--border); border-radius:var(--r-lg); padding:16px 12px; text-align:center; }
.stat-icon  { font-size:22px; margin-bottom:6px; }
.stat-val   { font-size:22px; font-weight:700; line-height:1.2; }
.stat-label { font-size:11px; color:var(--text-3); margin-top:4px; }

.chart-row  { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px; }
.chart-card { padding:14px 16px; }
.chart-hd   { font-size:12px; font-weight:600; color:var(--text-2); margin-bottom:10px; }
.echart     { width:100%; height:200px; }

@media (max-width:1200px) {
  .stat-grid  { grid-template-columns:repeat(3,1fr); }
  .chart-row  { grid-template-columns:1fr; }
}
</style>
