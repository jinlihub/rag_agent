<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { errMsg } from '@/api/http'
import { login, register } from '@/api/auth'
import { TEXTS } from '@/constants/texts'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const activeTab = ref<'login' | 'register'>('login')
const submitting = ref(false)

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  email: '',
  user_type: '自然人',
  display_name: '',
})

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 64, message: '长度 2-64 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '长度 6-64 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    {
      validator: (_rule: unknown, value: string, cb: (err?: Error) => void) => {
        if (!value) cb(new Error('请再次输入密码'))
        else if (value !== registerForm.password) cb(new Error('两次输入的密码不一致'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

const loginRef = ref()
const registerRef = ref()

async function doLogin() {
  try {
    await loginRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const { data } = await login(loginForm)
    auth.setAuth(data)
    goAfterAuth()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}

async function doRegister() {
  try {
    await registerRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const { data } = await register({
      username: registerForm.username,
      password: registerForm.password,
      email: registerForm.email || undefined,
      user_type: registerForm.user_type,
      display_name: registerForm.display_name || undefined,
    })
    auth.setAuth(data)
    goAfterAuth()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}

function goAfterAuth() {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/')) router.push(redirect)
  else if (auth.isAdmin) router.push('/admin/qa-list')
  else router.push('/chat')
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="brand-block">
        <BrandLogo :size="52" />
        <h1 class="title">Kael Mind</h1>
        <p class="subtitle">{{ TEXTS.appTitle }}</p>
      </div>
      <el-tabs v-model="activeTab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form ref="loginRef" :model="loginForm" :rules="loginRules" label-position="top" @submit.prevent>
            <el-form-item label="用户名" prop="username">
              <el-input v-model="loginForm.username" placeholder="用户名" data-testid="login-username" />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                show-password
                placeholder="密码"
                @keyup.enter="doLogin"
              />
            </el-form-item>
            <el-button type="primary" class="submit-btn" :loading="submitting" @click="doLogin">
              登 录
            </el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form ref="registerRef" :model="registerForm" :rules="registerRules" label-position="top" @submit.prevent>
            <el-form-item label="用户名" prop="username">
              <el-input v-model="registerForm.username" placeholder="2-64 个字符" />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="registerForm.password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-form-item label="确认密码" prop="confirmPassword">
              <el-input v-model="registerForm.confirmPassword" type="password" show-password />
            </el-form-item>
            <el-form-item label="用户角色">
              <el-radio-group v-model="registerForm.user_type">
                <el-radio value="自然人">自然人</el-radio>
                <el-radio value="企业用户">企业用户</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="名称">
              <el-input
                v-model="registerForm.display_name"
                :placeholder="registerForm.user_type === '企业用户' ? '如：XX公司' : '如：张工'"
              />
            </el-form-item>
            <el-form-item label="邮箱（选填）">
              <el-input v-model="registerForm.email" placeholder="name@example.com" />
            </el-form-item>
            <el-button type="primary" class="submit-btn" :loading="submitting" @click="doRegister">
              注 册
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #e8f3ff 0%, #f5f7fa 60%);
}

.login-card {
  width: 400px;
  padding: 8px 12px 4px;
}

.brand-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 8px 0 20px;
}

.title {
  text-align: center;
  font-size: 22px;
  font-weight: 650;
  letter-spacing: 0.3px;
  margin: 0;
  line-height: 1.2;
}

.subtitle {
  text-align: center;
  font-size: 13px;
  color: #909399;
  margin: 0;
}

.submit-btn {
  width: 100%;
  margin-top: 4px;
}
</style>
