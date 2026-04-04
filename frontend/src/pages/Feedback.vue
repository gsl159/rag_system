<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">用户反馈</div>
      <div class="page-sub">满意度统计 · 差评分析 · 持续优化</div>
    </div>
    <div class="page-body">
      <div v-if="!stats" class="loading-row"><span class="dots"><span/><span/><span/></span></div>
      <template v-else>
        <!-- 统计卡 -->
        <div class="stats-row">
          <div class="stat-mini card" v-for="s in statCards" :key="s.label">
            <div class="sm-val" :style="{color:s.color}">{{ s.val }}</div>
            <div class="sm-lbl">{{ s.label }}</div>
          </div>
        </div>

        <!-- 图表 -->
        <div class="chart-row">
          <div class="card chart-card">
            <div class="chart-hd">好评 vs 差评</div>
            <div ref="pieChart" class="echart"/>
          </div>
          <div class="card chart-card">
            <div class="chart-hd">用户满意度</div>
            <div ref="gaugeChart" class="echart"/>
          </div>
        </div>

        <!-- 差评Top -->
        <div class="card" style="margin-top:14px" v-if="stats.top_bad_queries?.length">
          <div class="section-hd" style="color:var(--red)">差评 Top 问题</div>
          <table class="data-table">
            <thead><tr><th>#</th><th>问题</th><th>备注</th></tr></thead>
            <tbody>
              <tr v-for="(item,i) in stats.top_bad_queries" :key="i">
                <td style="width:36px;color:var(--text-3)">{{ i+1 }}</td>
                <td>{{ item.query }}</td>
                <td style="color:var(--text-3)">{{ item.comment || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 最近反馈 -->
        <div class="card" style="margin-top:14px">
          <div class="section-hd">最近反馈</div>
          <div v-if="!stats.recent?.length" class="empty-row">暂无反馈数据</div>
          <table v-else class="data-table">
            <thead><tr><th>问题</th><th>评价</th><th>备注</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="(item,i) in stats.recent" :key="i">
                <td>{{ item.query }}</td>
                <td><span class="badge" :class="item.feedback==='like'?'badge-green':'badge-red'">{{ item.feedback==='like'?'👍 好评':'👎 差评' }}</span></td>
                <td style="color:var(--text-3)">{{ item.comment||'-' }}</td>
                <td style="font-size:11px;color:var(--text-3);white-space:nowrap">{{ fmtDate(item.time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFeedbackStats } from '@/api/index.js'

const stats = ref(null)
const pieChart = ref(null); const gaugeChart = ref(null)

const statCards = computed(() => !stats.value ? [] : [
  { label:'👍 好评', val:stats.value.like??0, color:'var(--green)' },
  { label:'👎 差评', val:stats.value.dislike??0, color:'var(--red)' },
  { label:'总反馈', val:stats.value.total??0, color:'var(--text-1)' },
  { label:'满意度', val:stats.value.satisfaction!=null?stats.value.satisfaction.toFixed(1)+'%':'-', color:'var(--yellow)' },
])

const T = { bg:'transparent', text:'#8b91a8', green:'#34d399', red:'#f87171', yellow:'#fbbf24' }

function drawPie(s) {
  const c = echarts.init(pieChart.value)
  c.setOption({
    backgroundColor:T.bg,
    tooltip:{ trigger:'item', formatter:'{b}: {c} ({d}%)' },
    legend:{ orient:'vertical', left:'left', textStyle:{ color:T.text, fontSize:11 } },
    series:[{ type:'pie', radius:['38%','68%'],
      data:[
        { value:s.like, name:'好评', itemStyle:{ color:T.green } },
        { value:s.dislike, name:'差评', itemStyle:{ color:T.red } },
      ],
      label:{ color:T.text, fontSize:11 },
    }]
  })
}
function drawGauge(s) {
  const val = parseFloat((s.satisfaction||0).toFixed(1))
  const c = echarts.init(gaugeChart.value)
  c.setOption({
    backgroundColor:T.bg,
    series:[{
      type:'gauge', startAngle:200, endAngle:-20, min:0, max:100,
      progress:{ show:true, width:18, itemStyle:{ color:val>=70?T.green:val>=50?T.yellow:T.red } },
      axisLine:{ lineStyle:{ width:18, color:[[1,'rgba(255,255,255,0.07)']] } },
      axisTick:{ show:false }, splitLine:{ show:false },
      axisLabel:{ color:T.text, distance:24, fontSize:10 },
      pointer:{ show:false },
      detail:{ valueAnimation:true, formatter:'{value}%', color:'#e8eaf0', fontSize:28, offsetCenter:[0,'20%'] },
      title:{ offsetCenter:[0,'52%'], color:T.text, fontSize:12 },
      data:[{ value:val, name:'满意度' }]
    }]
  })
}

function fmtDate(s) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false })
}

onMounted(async () => {
  try {
    stats.value = await apiFeedbackStats()
    await nextTick()
    if (pieChart.value)   drawPie(stats.value)
    if (gaugeChart.value) drawGauge(stats.value)
  } catch {
    stats.value = { like:0, dislike:0, total:0, satisfaction:0, recent:[], top_bad_queries:[] }
  }
})
</script>

<style scoped>
.loading-row { padding:60px; text-align:center; }
.stats-row   { display:flex; gap:12px; margin-bottom:14px; }
.stat-mini   { flex:1; text-align:center; padding:20px; }
.sm-val      { font-size:30px; font-weight:700; }
.sm-lbl      { font-size:12px; color:var(--text-3); margin-top:5px; }
.chart-row   { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.chart-card  { padding:14px 16px; }
.chart-hd    { font-size:12px; font-weight:600; color:var(--text-2); margin-bottom:10px; }
.echart      { width:100%; height:200px; }
.section-hd  { font-size:12px; font-weight:600; color:var(--text-2); margin-bottom:10px; }
.empty-row   { padding:24px; text-align:center; color:var(--text-3); font-size:13px; }
</style>
