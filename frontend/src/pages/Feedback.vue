<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">👍 用户反馈</div>
      <div class="page-sub">满意度统计 · 差评分析 · 改进闭环</div>
    </div>

    <div class="page-body">
      <!-- 统计卡 -->
      <div class="stats-row" v-if="stats">
        <div class="stat-mini card">
          <div class="sm-val" style="color:var(--green)">{{ stats.like ?? 0 }}</div>
          <div class="sm-lbl">👍 好评数</div>
        </div>
        <div class="stat-mini card">
          <div class="sm-val" style="color:var(--red)">{{ stats.dislike ?? 0 }}</div>
          <div class="sm-lbl">👎 差评数</div>
        </div>
        <div class="stat-mini card">
          <div class="sm-val" style="color:var(--blue)">{{ stats.total ?? 0 }}</div>
          <div class="sm-lbl">总反馈量</div>
        </div>
        <div class="stat-mini card">
          <div class="sm-val" style="color:var(--yellow)">
            {{ stats.satisfaction != null ? stats.satisfaction.toFixed(1) + '%' : '-' }}
          </div>
          <div class="sm-lbl">满意度</div>
        </div>
      </div>

      <!-- 图表行 -->
      <div class="chart-row" v-if="stats">
        <!-- 好差评饼图 -->
        <div class="card chart-card">
          <div class="chart-hd">👍👎 好评 vs 差评</div>
          <div ref="pieChart" class="echart" />
        </div>
        <!-- 满意度仪表盘 -->
        <div class="card chart-card">
          <div class="chart-hd">😊 用户满意度</div>
          <div ref="gaugeChart" class="echart" />
        </div>
      </div>

      <!-- Top 差评问题 -->
      <div class="card" style="margin-top:16px" v-if="stats?.top_bad_queries?.length">
        <div class="section-title">🔴 差评 Top 问题</div>
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>问题</th><th>用户备注</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, i) in stats.top_bad_queries" :key="i">
              <td style="width:36px;color:var(--text-3)">{{ i + 1 }}</td>
              <td>{{ item.query }}</td>
              <td style="color:var(--text-3)">{{ item.comment || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 最近反馈 -->
      <div class="card" style="margin-top:16px">
        <div class="section-title">🕐 最近反馈记录</div>
        <div v-if="!stats" class="empty"><p>加载中…</p></div>
        <div v-else-if="!stats.recent?.length" class="empty"><p>暂无反馈数据</p></div>
        <table v-else class="data-table">
          <thead>
            <tr><th>问题</th><th>评价</th><th>备注</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, i) in stats.recent" :key="i">
              <td>{{ item.query }}</td>
              <td>
                <span :class="['badge', item.feedback === 'like' ? 'badge-green' : 'badge-red']">
                  {{ item.feedback === 'like' ? '👍 好评' : '👎 差评' }}
                </span>
              </td>
              <td style="color:var(--text-3)">{{ item.comment || '-' }}</td>
              <td style="color:var(--text-3);font-size:11px;white-space:nowrap">{{ fmtDate(item.time) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 优化建议 -->
      <div class="card tip-card" style="margin-top:16px">
        <div class="tip-title">💡 闭环优化建议</div>
        <div class="tip-list">
          <div class="tip-item">
            <span class="tip-dot" style="background:var(--red)" />
            <span>差评高 → 检查检索召回率，调整 <code>CHUNK_SIZE</code> 或 <code>TOP_K</code></span>
          </div>
          <div class="tip-item">
            <span class="tip-dot" style="background:var(--yellow)" />
            <span>低相关性 → 优化 Query Rewrite Prompt 或补充文档</span>
          </div>
          <div class="tip-item">
            <span class="tip-dot" style="background:var(--blue)" />
            <span>忠实性低 → 调低 LLM temperature，增加 context 长度</span>
          </div>
          <div class="tip-item">
            <span class="tip-dot" style="background:var(--green)" />
            <span>缓存命中低 → 提高 <code>CACHE_TTL_RAG</code>，对相似 query 做归一化</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import * as echarts from 'echarts'
import { apiFeedbackStats } from '@/api/index.js'

const stats    = ref(null)
const pieChart  = ref(null)
const gaugeChart= ref(null)

const T = {
  bg: 'transparent', text: '#94a3b8',
  green: '#48bb78', red: '#fc8181', yellow: '#ecc94b'
}

function drawPie(s) {
  const chart = echarts.init(pieChart.value)
  chart.setOption({
    backgroundColor: T.bg,
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', textStyle: { color: T.text } },
    series: [{
      type: 'pie', radius: ['40%', '68%'],
      data: [
        { value: s.like,    name: '好评', itemStyle: { color: T.green  } },
        { value: s.dislike, name: '差评', itemStyle: { color: T.red    } },
      ],
      label: { color: T.text },
    }]
  })
}

function drawGauge(s) {
  const chart = echarts.init(gaugeChart.value)
  const val   = parseFloat((s.satisfaction || 0).toFixed(1))
  chart.setOption({
    backgroundColor: T.bg,
    series: [{
      type: 'gauge',
      startAngle: 200, endAngle: -20,
      min: 0, max: 100,
      progress: { show: true, width: 20, itemStyle: { color: val >= 70 ? T.green : val >= 50 ? T.yellow : T.red } },
      axisLine: { lineStyle: { width: 20, color: [[1, '#2d3748']] } },
      axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { color: T.text, distance: 28 },
      pointer:   { show: false },
      detail:    { valueAnimation: true, formatter: '{value}%', color: '#fff', fontSize: 30, offsetCenter: [0, '20%'] },
      title:     { offsetCenter: [0, '52%'], color: T.text, fontSize: 13 },
      data:      [{ value: val, name: '满意度' }]
    }]
  })
}

function fmtDate(s) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  try {
    stats.value = await apiFeedbackStats()
    await new Promise(r => setTimeout(r, 50))  // DOM ready
    drawPie(stats.value)
    drawGauge(stats.value)
  } catch (e) {
    stats.value = { like: 0, dislike: 0, total: 0, satisfaction: 0, recent: [], top_bad_queries: [] }
  }
})
</script>

<style scoped>
.stats-row  { display: flex; gap: 14px; margin-bottom: 16px; }
.stat-mini  { flex: 1; text-align: center; padding: 22px; }
.sm-val     { font-size: 34px; font-weight: 700; }
.sm-lbl     { font-size: 12px; color: var(--text-3); margin-top: 6px; }

.chart-row  { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.chart-card { padding: 16px 18px; }
.chart-hd   { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 10px; }
.echart     { width: 100%; height: 220px; }

.tip-card   { border-color: #1e3a1e; background: #0a1a0a; }
.tip-title  { font-weight: 600; color: var(--green); margin-bottom: 12px; }
.tip-list   { display: flex; flex-direction: column; gap: 10px; }
.tip-item   { display: flex; align-items: flex-start; gap: 10px; font-size: 13px; color: var(--text-2); }
.tip-dot    { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
code        { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; color: var(--accent-2); font-size: 12px; }
</style>
