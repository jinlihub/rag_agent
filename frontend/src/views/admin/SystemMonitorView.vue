<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getSystemMetrics } from '@/api/admin'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type { SystemMetrics } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const data = ref<SystemMetrics | null>(null)
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const logLevel = ref('ALL')
const logKeyword = ref('')

let timer: number | undefined

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const { data: snapshot } = await getSystemMetrics(200)
    data.value = snapshot
    error.value = ''
  } catch (e) {
    error.value = errMsg(e, '系统指标获取失败')
  } finally {
    loading.value = false
  }
}

function stopTimer() {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value) timer = window.setInterval(() => void refresh(), 5000)
}

function onAutoRefreshChange() {
  startTimer()
}

const filteredLogs = computed(() => {
  const keyword = logKeyword.value.trim().toLowerCase()
  return [...(data.value?.logs ?? [])]
    .reverse()
    .filter((item) => logLevel.value === 'ALL' || item.level === logLevel.value)
    .filter(
      (item) =>
        !keyword || `${item.logger} ${item.message}`.toLowerCase().includes(keyword),
    )
})

function pct(value?: number | null): number {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return 0
  return Math.min(100, Math.max(0, Math.round(n * 10) / 10))
}

function barColor(value?: number | null): string {
  const p = pct(value)
  if (p >= 90) return '#f56c6c'
  if (p >= 70) return '#e6a23c'
  return '#67c23a'
}

function fmtBytes(value?: number | null): string {
  if (value == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = Math.max(0, value)
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i += 1
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function mibToBytes(value?: number | null): number | null {
  return value == null ? null : value * 1024 * 1024
}

function fmtUptime(seconds?: number | null): string {
  if (seconds == null) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分钟`
}

function fmtTime(value?: string): string {
  return value ? value.replace('T', ' ') : '—'
}

function logTagType(level: string): 'success' | 'info' | 'warning' | 'danger' {
  if (level === 'ERROR' || level === 'CRITICAL') return 'danger'
  if (level === 'WARNING') return 'warning'
  if (level === 'INFO') return 'success'
  return 'info'
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(() => {
  void refresh()
  startTimer()
})

onBeforeUnmount(stopTimer)
</script>

<template>
  <div class="monitor-page">
    <header class="admin-header">
      <div class="system-name">招投标问答机器人管理后台</div>
      <div class="user-zone">
        <el-button link type="primary" @click="router.push('/admin/qa-list')">问答维护</el-button>
        <el-button link type="primary" @click="router.push('/chat')">返回问答</el-button>
        <el-tag size="small" type="info" effect="plain">管理员</el-tag>
        <span class="username">{{ auth.user?.display_name }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <div v-loading="loading && !data" class="monitor-body">
      <div class="toolbar">
        <el-breadcrumb>
          <el-breadcrumb-item>首页</el-breadcrumb-item>
          <el-breadcrumb-item>系统监控</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="refresh-zone">
          <span class="muted">更新于 {{ fmtTime(data?.timestamp) }}</span>
          <el-switch v-model="autoRefresh" active-text="自动刷新" @change="onAutoRefreshChange" />
          <el-button :loading="loading" @click="refresh">刷新</el-button>
        </div>
      </div>

      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="error-bar"
      />

      <template v-if="data">
        <div class="metric-grid">
          <el-card shadow="never" class="metric-card">
            <template #header>
              <div class="card-head">
                <span>CPU</span>
                <span class="muted">{{ data.cpu.logical }} 逻辑核 / {{ data.cpu.physical }} 物理核</span>
              </div>
            </template>
            <div class="metric-body">
              <el-progress
                type="dashboard"
                :percentage="pct(data.cpu.percent)"
                :color="barColor(data.cpu.percent)"
                :width="118"
              />
              <div class="metric-info">
                <div class="metric-line"><span>使用率</span><b>{{ data.cpu.percent.toFixed(1) }}%</b></div>
                <div class="metric-line">
                  <span>负载均值</span><b>{{ data.host.load_avg?.join(' / ') ?? '—' }}</b>
                </div>
                <div class="core-strip" :title="`每核使用率：${data.cpu.per_core.join('%, ')}%`">
                  <span
                    v-for="(value, index) in data.cpu.per_core"
                    :key="index"
                    class="core-cell"
                    :style="{ opacity: 0.2 + (pct(value) / 100) * 0.8 }"
                  />
                </div>
              </div>
            </div>
          </el-card>

          <el-card shadow="never" class="metric-card">
            <template #header>
              <div class="card-head"><span>内存</span><span class="muted">物理内存 / Swap</span></div>
            </template>
            <div class="metric-body">
              <el-progress
                type="dashboard"
                :percentage="pct(data.memory.percent)"
                :color="barColor(data.memory.percent)"
                :width="118"
              />
              <div class="metric-info">
                <div class="metric-line">
                  <span>已用 / 总量</span><b>{{ fmtBytes(data.memory.used) }} / {{ fmtBytes(data.memory.total) }}</b>
                </div>
                <div class="metric-line"><span>可用</span><b>{{ fmtBytes(data.memory.available) }}</b></div>
                <div class="metric-line">
                  <span>Swap</span>
                  <b>{{ fmtBytes(data.swap.used) }} / {{ fmtBytes(data.swap.total) }}（{{ data.swap.percent.toFixed(1) }}%）</b>
                </div>
              </div>
            </div>
          </el-card>

          <el-card shadow="never" class="metric-card">
            <template #header>
              <div class="card-head"><span>磁盘</span><span class="muted">{{ data.disk.path }}</span></div>
            </template>
            <div class="metric-body">
              <el-progress
                type="dashboard"
                :percentage="pct(data.disk.percent)"
                :color="barColor(data.disk.percent)"
                :width="118"
              />
              <div class="metric-info">
                <div class="metric-line">
                  <span>已用 / 总量</span><b>{{ fmtBytes(data.disk.used) }} / {{ fmtBytes(data.disk.total) }}</b>
                </div>
                <div class="metric-line"><span>可用</span><b>{{ fmtBytes(data.disk.free) }}</b></div>
              </div>
            </div>
            <div class="partition-list">
              <div v-for="part in data.disk.partitions" :key="part.mountpoint" class="partition-row">
                <span class="partition-name">{{ part.mountpoint }}</span>
                <el-progress
                  class="partition-bar"
                  :percentage="pct(part.percent)"
                  :color="barColor(part.percent)"
                  :stroke-width="6"
                  :show-text="false"
                />
                <span class="partition-pct">{{ part.percent.toFixed(1) }}%</span>
              </div>
            </div>
          </el-card>

          <el-card shadow="never" class="metric-card">
            <template #header>
              <div class="card-head">
                <span>GPU</span>
                <span class="muted">{{ data.gpu.available ? `${data.gpu.items.length} 张显卡` : '未检测到 NVIDIA GPU' }}</span>
              </div>
            </template>
            <div v-if="data.gpu.items.length" class="gpu-list">
              <div v-for="gpu in data.gpu.items" :key="gpu.index ?? gpu.name" class="gpu-item">
                <div class="gpu-head">
                  <span>{{ gpu.name }}</span>
                  <span class="muted">{{ gpu.temperature != null ? `${gpu.temperature}°C` : '—' }}</span>
                </div>
                <el-progress
                  :percentage="pct(gpu.utilization)"
                  :color="barColor(gpu.utilization)"
                  :stroke-width="8"
                />
                <div class="metric-line">
                  <span>显存</span>
                  <b>{{ fmtBytes(mibToBytes(gpu.memory_used)) }} / {{ fmtBytes(mibToBytes(gpu.memory_total)) }}</b>
                </div>
              </div>
            </div>
            <div v-else class="empty-gpu">{{ data.gpu.message || '未检测到 NVIDIA GPU' }}</div>
          </el-card>
        </div>

        <el-card shadow="never" class="info-card">
          <template #header>
            <div class="card-head"><span>运行信息</span><span class="muted">{{ data.host.platform }}</span></div>
          </template>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="主机名">{{ data.host.hostname }}</el-descriptions-item>
            <el-descriptions-item label="Python">{{ data.host.python }}</el-descriptions-item>
            <el-descriptions-item label="系统运行">{{ fmtUptime(data.host.uptime_seconds) }}</el-descriptions-item>
            <el-descriptions-item label="启动时间">{{ fmtTime(data.host.boot_time) }}</el-descriptions-item>
            <el-descriptions-item label="服务进程">PID {{ data.process.pid }} · {{ data.process.name }}</el-descriptions-item>
            <el-descriptions-item label="进程运行">{{ fmtUptime(data.process.uptime_seconds) }}</el-descriptions-item>
            <el-descriptions-item label="进程 CPU">{{ data.process.cpu_percent.toFixed(1) }}%</el-descriptions-item>
            <el-descriptions-item label="进程内存">
              {{ fmtBytes(data.process.memory_rss) }}（{{ data.process.memory_percent.toFixed(1) }}%）
            </el-descriptions-item>
            <el-descriptions-item label="线程数">{{ data.process.threads }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card shadow="never" class="log-card">
          <template #header>
            <div class="card-head">
              <span>近期日志</span>
              <div class="log-tools">
                <el-select v-model="logLevel" size="small" style="width: 112px">
                  <el-option label="全部级别" value="ALL" />
                  <el-option label="INFO" value="INFO" />
                  <el-option label="WARNING" value="WARNING" />
                  <el-option label="ERROR" value="ERROR" />
                </el-select>
                <el-input
                  v-model="logKeyword"
                  size="small"
                  placeholder="过滤来源 / 内容"
                  clearable
                  style="width: 200px"
                />
                <span class="muted">{{ filteredLogs.length }} 条</span>
              </div>
            </div>
          </template>
          <el-table :data="filteredLogs" height="340" size="small">
            <el-table-column prop="time" label="时间" width="170" />
            <el-table-column prop="level" label="级别" width="92">
              <template #default="{ row }">
                <el-tag size="small" :type="logTagType(row.level)">{{ row.level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="logger" label="来源" width="190" show-overflow-tooltip />
            <el-table-column prop="message" label="内容" min-width="320" show-overflow-tooltip />
            <template #empty>暂无日志（服务启动后的 root / rag_agent / uvicorn 日志会显示在这里）</template>
          </el-table>
        </el-card>
      </template>
      <el-empty v-else-if="!loading" description="暂无监控数据" />
    </div>
  </div>
</template>

<style scoped>
.monitor-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.admin-header {
  height: var(--app-header-height);
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.system-name {
  font-weight: 600;
  font-size: 16px;
}

.user-zone {
  display: flex;
  align-items: center;
  gap: 10px;
}

.username {
  color: #606266;
}

.monitor-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.refresh-zone {
  display: flex;
  align-items: center;
  gap: 12px;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.error-bar {
  margin-bottom: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.info-card,
.log-card {
  margin-bottom: 12px;
}

.metric-body {
  display: flex;
  align-items: center;
  gap: 20px;
}

.metric-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}

.metric-line b {
  color: #303133;
  font-weight: 500;
  text-align: right;
  word-break: break-all;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.core-strip {
  display: flex;
  gap: 2px;
  height: 8px;
}

.core-cell {
  flex: 1;
  min-width: 2px;
  border-radius: 1px;
  background: #409eff;
}

.partition-list {
  margin-top: 12px;
  border-top: 1px dashed #e4e7ed;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.partition-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #606266;
}

.partition-name {
  width: 64px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.partition-bar {
  flex: 1;
  min-width: 0;
}

.partition-pct {
  width: 44px;
  flex: none;
  text-align: right;
}

.gpu-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gpu-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gpu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: #303133;
}

.empty-gpu {
  color: #909399;
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}

.log-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.info-card :deep(.el-descriptions__label) {
  width: 92px;
}

@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .toolbar {
    align-items: flex-start;
    gap: 10px;
    flex-direction: column;
  }
}
</style>
