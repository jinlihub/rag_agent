<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { approveCluster, editAnswer, listClusters, listQa, markCorrect, noNeed } from '@/api/admin'
import { errMsg } from '@/api/http'
import { TEXTS } from '@/constants/texts'
import { useAuthStore } from '@/stores/auth'
import type { QaCluster, QaRecord } from '@/types'

const router = useRouter()
const auth = useAuthStore()

/** 视图切换：问答列表（逐条维护）/ 按簇处理（批量消化积压） */
const activeTab = ref<'list' | 'cluster'>('list')
const clusters = ref<QaCluster[]>([])
const clusterTotal = ref(0)
const clusterQuestionTotal = ref(0)
const clusterLoading = ref(false)
const approvingId = ref<number | null>(null)

/** 筛选默认态对齐设计稿 p12：维护结果=未维护、结果评价=无 */
const filters = reactive({
  username: '',
  keyword: '',
  user_type: '',
  maintain_status: '未维护',
  result_evaluation: '无',
  range: null as [string, string] | null,
})

const page = reactive({ current: 1, size: 20 })
const total = ref(0)
const rows = ref<QaRecord[]>([])
const loading = ref(false)

const editVisible = ref(false)
const editForm = reactive({ id: 0, question: '', answer: '' })
const editSubmitting = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const { data } = await listQa({
      username: filters.username || undefined,
      keyword: filters.keyword || undefined,
      user_type: filters.user_type || undefined,
      maintain_status: filters.maintain_status || undefined,
      result_evaluation: filters.result_evaluation || undefined,
      date_from: filters.range?.[0],
      date_to: filters.range?.[1],
      page: page.current,
      page_size: page.size,
    })
    total.value = data.total
    rows.value = data.items
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function search() {
  page.current = 1
  void fetchList()
}

function reset() {
  Object.assign(filters, {
    username: '',
    keyword: '',
    user_type: '',
    maintain_status: '未维护',
    result_evaluation: '无',
    range: null,
  })
  search()
}

async function onMarkCorrect(row: QaRecord) {
  try {
    await markCorrect(row.id)
    ElMessage.success(TEXTS.markCorrectDone)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
  void fetchList()
}

function onNoNeed(row: QaRecord) {
  ElMessageBox.confirm(TEXTS.confirmNoNeed, '提示', { type: 'warning' })
    .then(async () => {
      try {
        await noNeed(row.id)
        ElMessage.success(TEXTS.noNeedDone)
      } catch (e) {
        ElMessage.error(errMsg(e))
      }
      void fetchList()
    })
    .catch(() => {})
}

function onEdit(row: QaRecord) {
  editForm.id = row.id
  editForm.question = row.question
  editForm.answer = row.answer ?? ''
  editVisible.value = true
}

async function saveEdit() {
  if (!editForm.answer.trim()) {
    ElMessage.warning(TEXTS.answerRequired)
    return
  }
  editSubmitting.value = true
  try {
    await editAnswer(editForm.id, editForm.answer.trim())
    ElMessage.success(TEXTS.saveDone)
    editVisible.value = false
    void fetchList()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    editSubmitting.value = false
  }
}

async function fetchClusters() {
  clusterLoading.value = true
  try {
    const { data } = await listClusters()
    clusters.value = data.items
    clusterTotal.value = data.total
    clusterQuestionTotal.value = data.total_questions
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    clusterLoading.value = false
  }
}

/** 切到「按簇处理」时才拉簇数据，避免进页面就打一次聚类查询 */
function onTabChange(name: string | number) {
  if (name === 'cluster') void fetchClusters()
}

function onApproveCluster(cluster: QaCluster) {
  ElMessageBox.confirm(
    `${TEXTS.confirmApproveCluster}（本簇 ${cluster.size} 条）`,
    '一键确认',
    { type: 'warning' },
  )
    .then(async () => {
      approvingId.value = cluster.id
      try {
        const { data } = await approveCluster(cluster.id)
        ElMessage.success(`已确认 ${data.updated} 条`)
        void fetchClusters()
        void fetchList()
      } catch (e) {
        ElMessage.error(errMsg(e))
      } finally {
        approvingId.value = null
      }
    })
    .catch(() => {})
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(fetchList)
</script>

<template>
  <div class="admin-page">
    <header class="admin-header">
      <div class="system-name">招投标问答机器人管理后台</div>
      <div class="user-zone">
        <el-button link type="primary" @click="router.push('/admin/system')">系统监控</el-button>
        <el-button link type="primary" @click="router.push('/chat')">返回问答</el-button>
        <el-tag size="small" type="info" effect="plain">管理员</el-tag>
        <span class="username">{{ auth.user?.display_name }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <div class="admin-body">
      <el-breadcrumb class="breadcrumb">
        <el-breadcrumb-item>首页</el-breadcrumb-item>
        <el-breadcrumb-item>用户问答列表</el-breadcrumb-item>
      </el-breadcrumb>

      <el-tabs v-model="activeTab" class="admin-tabs" @tab-change="onTabChange">
        <el-tab-pane label="问答列表" name="list">
          <el-card shadow="never" class="filter-card">
            <el-form inline @submit.prevent>
              <el-form-item label="用户名称">
                <el-input v-model="filters.username" placeholder="用户名 / 名称" clearable style="width: 160px" @keyup.enter="search" />
              </el-form-item>
              <el-form-item label="问题关键词">
                <el-input v-model="filters.keyword" placeholder="问题关键词" clearable style="width: 180px" @keyup.enter="search" />
              </el-form-item>
              <el-form-item label="用户角色">
                <el-select v-model="filters.user_type" style="width: 120px">
                  <el-option label="全部" value="" />
                  <el-option label="企业用户" value="企业用户" />
                  <el-option label="自然人" value="自然人" />
                </el-select>
              </el-form-item>
              <el-form-item label="维护结果">
                <el-select v-model="filters.maintain_status" style="width: 130px">
                  <el-option label="全部" value="" />
                  <el-option label="未维护" value="未维护" />
                  <el-option label="已维护" value="已维护" />
                  <el-option label="不需要维护" value="不需要维护" />
                </el-select>
              </el-form-item>
              <el-form-item label="结果评价">
                <el-select v-model="filters.result_evaluation" style="width: 100px">
                  <el-option label="全部" value="" />
                  <el-option label="无" value="无" />
                  <el-option label="赞" value="赞" />
                  <el-option label="踩" value="踩" />
                </el-select>
              </el-form-item>
              <el-form-item label="问题时间">
                <el-date-picker
                  v-model="filters.range"
                  type="daterange"
                  value-format="YYYY-MM-DD"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                  style="width: 240px"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="loading" @click="search">查询</el-button>
                <el-button @click="reset">重置</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card shadow="never">
            <el-table :data="rows" v-loading="loading" style="width: 100%">
              <el-table-column type="index" label="序号" width="60" />
              <el-table-column prop="question" label="用户问题" min-width="220" show-overflow-tooltip />
              <el-table-column prop="answer" label="智能回答" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ row.answer ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="用户" width="140" show-overflow-tooltip>
                <template #default="{ row }">{{ row.display_name || row.username }}</template>
              </el-table-column>
              <el-table-column prop="user_type" label="用户角色" width="100" />
              <el-table-column label="维护结果" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.maintain_status === '未维护' ? 'warning' : row.maintain_status === '已维护' ? 'success' : 'info'" size="small">
                    {{ row.maintain_status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="创建时间" width="170" />
              <el-table-column prop="updated_at" label="修改时间" width="170" />
              <el-table-column label="操作" width="200" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="onMarkCorrect(row as QaRecord)">标记正确</el-button>
                  <el-button link type="primary" @click="onEdit(row as QaRecord)">编辑</el-button>
                  <el-button link type="danger" @click="onNoNeed(row as QaRecord)">不需要维护</el-button>
                </template>
              </el-table-column>
              <template #empty>{{ TEXTS.adminListEmpty }}</template>
            </el-table>

            <el-pagination
              v-model:current-page="page.current"
              v-model:page-size="page.size"
              class="pagination"
              :total="total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="fetchList"
              @size-change="search"
            />
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="按簇处理" name="cluster">
          <el-alert
            class="cluster-tip"
            type="info"
            :closable="false"
            show-icon
            title="草稿由 scripts/cluster_unmaintained.py 离线生成；一键确认后簇内问题全部置为「已维护」。"
          />
          <div class="cluster-toolbar">
            <span class="cluster-count">
              共 {{ clusterTotal }} 簇 / {{ clusterQuestionTotal }} 条已起草的未维护问题
            </span>
            <el-button :loading="clusterLoading" @click="fetchClusters">刷新</el-button>
          </div>
          <div v-loading="clusterLoading" class="cluster-grid">
            <el-empty
              v-if="!clusterLoading && !clusters.length"
              :description="TEXTS.clusterListEmpty"
              class="cluster-empty"
            />
            <el-card v-for="cluster in clusters" :key="cluster.id" shadow="never" class="cluster-card">
              <div class="cluster-head">
                <el-tag type="warning" size="small">{{ cluster.size }} 条</el-tag>
                <span class="cluster-id">簇 #{{ cluster.id }}</span>
                <el-button
                  type="primary"
                  size="small"
                  :loading="approvingId === cluster.id"
                  @click="onApproveCluster(cluster)"
                >
                  一键确认
                </el-button>
              </div>
              <ul class="cluster-samples">
                <li v-for="(question, idx) in cluster.questions" :key="idx">{{ question }}</li>
                <li v-if="cluster.size > cluster.questions.length" class="cluster-more">
                  …另有 {{ cluster.size - cluster.questions.length }} 条相似问题
                </li>
              </ul>
              <el-divider class="cluster-divider" />
              <div class="cluster-draft">{{ cluster.draft }}</div>
            </el-card>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="editVisible" title="编辑智能回答" width="640px">
      <div class="edit-question">原问题：{{ editForm.question }}</div>
      <el-input
        v-model="editForm.answer"
        type="textarea"
        :rows="8"
        maxlength="20000"
        show-word-limit
        placeholder="修正后的回答内容"
      />
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page {
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

.admin-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.breadcrumb {
  margin-bottom: 12px;
}

.filter-card {
  margin-bottom: 12px;
}

.filter-card :deep(.el-form-item) {
  margin-bottom: 8px;
}

.pagination {
  margin-top: 14px;
  justify-content: flex-end;
}

.edit-question {
  color: #909399;
  margin-bottom: 10px;
  line-height: 1.6;
  word-break: break-all;
}

/* ── 按簇处理 ───────────────────────────────────────────────────────────── */

.cluster-tip {
  margin-bottom: 12px;
}

.cluster-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.cluster-count {
  color: #606266;
}

.cluster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 12px;
  min-height: 160px;
}

.cluster-empty {
  grid-column: 1 / -1;
}

.cluster-card :deep(.el-card__body) {
  padding: 14px 16px;
}

.cluster-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cluster-id {
  margin-right: auto;
  color: #909399;
  font-size: 12px;
}

.cluster-samples {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
}

.cluster-samples li::before {
  content: '· ';
}

.cluster-more {
  color: #909399;
}

.cluster-divider {
  margin: 10px 0;
}

.cluster-draft {
  max-height: 260px;
  overflow-y: auto;
  color: #303133;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
}
</style>
