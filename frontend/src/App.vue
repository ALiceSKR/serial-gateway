<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const user = ref(null)
const loginForm = reactive({ username: '', password: '' })
const loginError = ref('')
const busy = ref(false)
const settingsOpen = ref(false)
const managerView = ref('list')
const deleteMode = ref(false)
const portDraft = ref(null)
const editingOriginalId = ref(null)
const config = reactive({ ports: [] })
const devices = ref([])
const selectedId = ref('')
const statuses = ref([])
const terminalHost = ref(null)
const hostname = window.location.hostname
let socket
let statusTimer
let xterm
let fitAddon
let resizeObserver
const terminalHistory = new Map()

const selected = computed(() => config.ports.find(port => port.id === selectedId.value) || config.ports[0] || {})
const currentStatus = computed(() => statuses.value.find(item => item.port_id === selectedId.value) || {})
const connectionLabel = computed(() => !currentStatus.value.enabled ? 'CLOSED' : currentStatus.value.serial_connected ? 'ONLINE' : 'OFFLINE')
const baudrates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000, 1500000, 2000000, 3000000, 4000000]

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (response.status === 401) {
    disconnectSocket()
    destroyTerminal()
    user.value = null
    throw new Error('请重新登录')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `请求失败 (${response.status})`)
  }
  return response.json()
}

async function login() {
  busy.value = true
  loginError.value = ''
  try {
    user.value = await api('/api/login', { method: 'POST', body: JSON.stringify(loginForm) })
    await loadDashboard()
  } catch (error) {
    loginError.value = error.message
  } finally {
    busy.value = false
  }
}

async function logout() {
  await api('/api/logout', { method: 'POST' }).catch(() => {})
  disconnectSocket()
  destroyTerminal()
  user.value = null
}

async function loadDashboard() {
  Object.assign(config, await api('/api/settings'))
  devices.value = await api('/api/devices')
  if (!config.ports.some(port => port.id === selectedId.value)) selectedId.value = config.ports[0]?.id || ''
  await refreshStatus()
  await nextTick()
  initTerminal()
  connectSocket()
  clearInterval(statusTimer)
  statusTimer = setInterval(refreshStatus, 3000)
}

async function refreshStatus() {
  try { statuses.value = await api('/api/status') } catch (_) { /* handled by api */ }
}

function connectSocket() {
  disconnectSocket()
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${scheme}://${location.host}/ws/terminal`)
  socket.onopen = () => {
    xterm?.focus()
  }
  socket.onmessage = ({ data }) => {
    const event = JSON.parse(data)
    const portId = event.port_id === '*' ? selectedId.value : event.port_id
    let output = ''
    if (event.source === 'UART RX') {
      output = event.data
    }
    if (output) appendTerminal(portId, output)
  }
  socket.onclose = () => {
    if (user.value) setTimeout(connectSocket, 1500)
  }
}

function initTerminal() {
  if (xterm || !terminalHost.value) return
  xterm = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: "'IBM Plex Mono', 'DejaVu Sans Mono', monospace",
    fontSize: 14,
    lineHeight: 1.25,
    scrollback: 5000,
    theme: {
      background: '#07110e', foreground: '#c9d8d3', cursor: '#55e6ad',
      cursorAccent: '#07110e', selectionBackground: '#55e6ad44',
      black: '#07110e', red: '#ff665f', green: '#55e6ad', yellow: '#d9ac4f',
      blue: '#6ebcff', magenta: '#b186ff', cyan: '#55dce6', white: '#d8e2df',
    },
  })
  fitAddon = new FitAddon()
  xterm.loadAddon(fitAddon)
  xterm.open(terminalHost.value)
  fitAddon.fit()
  xterm.onData((data) => sendTerminalData(data))
  resizeObserver = new ResizeObserver(() => fitAddon?.fit())
  resizeObserver.observe(terminalHost.value)
}

function sendTerminalData(data) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ port_id: selectedId.value, data }))
  } else {
    xterm?.writeln('\r\n\x1b[31m[WebSocket 未连接]\x1b[0m')
  }
}

function appendTerminal(portId, data) {
  const existing = terminalHistory.get(portId) || ''
  const combined = existing + data
  terminalHistory.set(portId, combined.length > 1_000_000 ? combined.slice(-800_000) : combined)
  if (portId === selectedId.value) xterm?.write(data)
}

function clearTerminal() {
  terminalHistory.set(selectedId.value, '')
  xterm?.reset()
  xterm?.focus()
}

function disconnectSocket() {
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
  clearInterval(statusTimer)
}

function destroyTerminal() {
  resizeObserver?.disconnect()
  resizeObserver = null
  xterm?.dispose()
  xterm = null
  fitAddon = null
  terminalHistory.clear()
}

async function persistPorts(ports) {
  busy.value = true
  try {
    const payload = { ports: ports.map(port => ({ ...port, baudrate: Number(port.baudrate), bytesize: Number(port.bytesize), stopbits: Number(port.stopbits), telnet_port: Number(port.telnet_port) })) }
    Object.assign(config, await api('/api/settings', { method: 'PUT', body: JSON.stringify(payload) }))
    devices.value = await api('/api/devices')
    await refreshStatus()
    return true
  } catch (error) {
    alert(error.message)
    return false
  } finally {
    busy.value = false
  }
}

function openManager() {
  settingsOpen.value = true
  managerView.value = 'list'
  deleteMode.value = false
  portDraft.value = null
}

function closeOrBackManager() {
  if (managerView.value === 'edit') {
    managerView.value = 'list'
    portDraft.value = null
    editingOriginalId.value = null
  } else {
    settingsOpen.value = false
  }
}

function editPort(port) {
  editingOriginalId.value = port.id
  portDraft.value = JSON.parse(JSON.stringify(port))
  managerView.value = 'edit'
}

function addPort() {
  let number = config.ports.length
  while (config.ports.some(port => port.id === `uart${number}`)) number++
  editingOriginalId.value = null
  portDraft.value = { id: `uart${number}`, name: `UART ${number}`, device: devices.value[number]?.device || `/dev/ttyUSB${number}`, telnet_port: 2000 + number, baudrate: 115200, bytesize: 8, parity: 'N', stopbits: 1, simulated: false, enabled: true }
  managerView.value = 'edit'
}

async function savePort() {
  const draft = JSON.parse(JSON.stringify(portDraft.value))
  const ports = editingOriginalId.value
    ? config.ports.map(port => port.id === editingOriginalId.value ? draft : port)
    : [...config.ports, draft]
  if (!await persistPorts(ports)) return
  if (editingOriginalId.value && editingOriginalId.value !== draft.id) {
    terminalHistory.set(draft.id, terminalHistory.get(editingOriginalId.value) || '')
    terminalHistory.delete(editingOriginalId.value)
    if (selectedId.value === editingOriginalId.value) selectedId.value = draft.id
  }
  managerView.value = 'list'
}

async function deletePort(port) {
  if (config.ports.length <= 1) return
  if (!window.confirm(`确定删除通道“${port.name}”吗？`)) return
  const ports = config.ports.filter(item => item.id !== port.id)
  if (!await persistPorts(ports)) return
  terminalHistory.delete(port.id)
  if (selectedId.value === port.id) selectedId.value = config.ports[0].id
}

async function toggleCurrentPort() {
  const opening = !currentStatus.value.enabled
  busy.value = true
  try {
    await api(`/api/ports/${encodeURIComponent(selectedId.value)}/${opening ? 'open' : 'close'}`, { method: 'POST' })
    const port = config.ports.find(item => item.id === selectedId.value)
    if (port) port.enabled = opening
    await refreshStatus()
  } catch (error) {
    alert(error.message)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    user.value = await api('/api/me')
    await loadDashboard()
  } catch (_) { user.value = null }
})
watch(selectedId, async (newId, oldId) => {
  if (!xterm || !oldId || newId === oldId) return
  xterm.reset()
  const history = terminalHistory.get(newId)
  if (history) xterm.write(history)
  await nextTick()
  fitAddon?.fit()
  xterm.focus()
})

onBeforeUnmount(() => {
  disconnectSocket()
  destroyTerminal()
})
</script>

<template>
  <main v-if="!user" class="login-page">
    <section class="login-card">
      <div class="brand-mark">SG</div>
      <p class="eyebrow">AI SHARED INFRASTRUCTURE</p>
      <h1>Serial Gateway</h1>
      <p class="muted">登录以访问共享串口控制台</p>
      <form @submit.prevent="login">
        <label>用户名<input v-model="loginForm.username" autocomplete="username" /></label>
        <label>密码<input v-model="loginForm.password" type="password" autocomplete="current-password" /></label>
        <p v-if="loginError" class="error">{{ loginError }}</p>
        <button class="primary full" :disabled="busy">{{ busy ? '登录中…' : '进入控制台' }}</button>
      </form>
    </section>
  </main>

  <main v-else class="dashboard">
    <header>
      <div class="header-brand"><span class="mini-mark">SG</span><div><strong>Serial Gateway</strong><small>UART OPERATIONS CONSOLE</small></div></div>
      <div class="header-actions">
        <span :class="['status-pill', currentStatus.serial_connected ? 'online' : 'offline']"><i></i>{{ connectionLabel }}</span>
        <button class="ghost" @click="openManager">串口设置</button>
        <button class="avatar" title="退出登录" @click="logout">{{ user.username.slice(0, 1).toUpperCase() }}</button>
      </div>
    </header>

    <nav class="channel-tabs">
      <button v-for="port in config.ports" :key="port.id" :class="{ active: selectedId === port.id }" @click="selectedId = port.id">
        <i :class="statuses.find(s => s.port_id === port.id)?.serial_connected ? 'connected' : ''"></i>{{ port.name }}<small>:{{ port.telnet_port }}</small>
      </button>
      <button class="add-channel" @click="openManager">＋ 管理通道</button>
    </nav>

    <section class="overview">
      <div><span class="label">ACTIVE DEVICE</span><strong>{{ selected.device }}</strong></div>
      <div><span class="label">SERIAL FORMAT</span><strong>{{ selected.baudrate }} · {{ selected.bytesize }}{{ selected.parity }}{{ selected.stopbits }}</strong></div>
      <div><span class="label">TELNET ENDPOINT</span><strong>{{ hostname }}:{{ selected.telnet_port }}</strong></div>
      <div><span class="label">CONNECTED CLIENTS</span><strong>{{ currentStatus.telnet_clients || 0 }} Telnet · 1 Web</strong></div>
    </section>

    <section class="console-card">
      <div class="console-head">
        <div><span class="window-dot red"></span><span class="window-dot amber"></span><span class="window-dot green"></span><b>INTERACTIVE LINUX CONSOLE</b></div>
        <div class="terminal-actions">
          <span>点击终端直接输入 · 支持 Tab / Ctrl+C / 方向键</span>
          <button :class="['port-power', currentStatus.enabled ? 'close-port' : 'open-port']" :disabled="busy" @click="toggleCurrentPort">{{ currentStatus.enabled ? '关闭串口' : '打开串口' }}</button>
          <button class="text-button" @click="clearTerminal">清屏</button>
        </div>
      </div>
      <div ref="terminalHost" class="terminal xterm-host" @click="xterm?.focus()"></div>
    </section>
    <p v-if="currentStatus.last_error" class="status-error">{{ currentStatus.last_error }}</p>

    <div v-if="settingsOpen" class="modal-backdrop" @click.self="settingsOpen = false">
      <section class="settings-card">
        <div class="modal-head">
          <div><p class="eyebrow">SERIAL CHANNELS</p><h2>{{ managerView === 'list' ? '管理通道' : editingOriginalId ? '编辑串口' : '添加串口' }}</h2></div>
          <button type="button" class="close" :title="managerView === 'list' ? '关闭' : '返回列表'" @click="closeOrBackManager">×</button>
        </div>

        <template v-if="managerView === 'list'">
          <div class="channel-list">
            <div v-for="port in config.ports" :key="port.id" :class="['channel-row', { deleting: deleteMode }]" role="button" tabindex="0" @click="editPort(port)" @keydown.enter="editPort(port)">
              <span :class="['channel-state', statuses.find(item => item.port_id === port.id)?.serial_connected ? 'connected' : '']"></span>
              <span class="channel-main"><strong>{{ port.name }}</strong><small>{{ port.device }} · {{ port.baudrate }} {{ port.bytesize }}{{ port.parity }}{{ port.stopbits }}</small></span>
              <span class="channel-port">TELNET :{{ port.telnet_port }}</span>
              <button v-if="deleteMode" type="button" class="row-delete" :disabled="config.ports.length === 1" @click.stop="deletePort(port)">删除</button>
              <span v-else class="row-edit">编辑 ›</span>
            </div>
          </div>
          <div class="manager-actions">
            <button type="button" class="add-port" @click="addPort">＋ 添加串口</button>
            <button type="button" :class="['delete-toggle', { active: deleteMode }]" @click="deleteMode = !deleteMode">{{ deleteMode ? '完成删除' : '删除通道' }}</button>
          </div>
        </template>

        <form v-else-if="portDraft" @submit.prevent="savePort">
          <div class="form-grid edit-form">
            <label>通道 ID<input v-model="portDraft.id" placeholder="uart0" /></label>
            <label>显示名称<input v-model="portDraft.name" placeholder="Console UART" /></label>
            <label class="device-field">设备路径
              <select v-model="portDraft.device">
                <option v-if="!devices.some(item => item.device === portDraft.device)" :value="portDraft.device">{{ portDraft.device }} · 当前配置</option>
                <option v-for="item in devices" :key="item.device" :value="item.device">{{ item.display_name }}</option>
              </select>
            </label>
            <label>Telnet 端口<input v-model.number="portDraft.telnet_port" type="number" min="1024" max="65535" /></label>
            <label>波特率<select v-model.number="portDraft.baudrate"><option v-for="rate in baudrates" :key="rate" :value="rate">{{ rate }}</option></select></label>
            <label>数据位<select v-model.number="portDraft.bytesize"><option v-for="n in [5,6,7,8]" :key="n">{{ n }}</option></select></label>
            <label>校验位<select v-model="portDraft.parity"><option value="N">None</option><option value="E">Even</option><option value="O">Odd</option><option value="M">Mark</option><option value="S">Space</option></select></label>
            <label>停止位<select v-model.number="portDraft.stopbits"><option :value="1">1</option><option :value="1.5">1.5</option><option :value="2">2</option></select></label>
          </div>
          <div class="modal-actions"><button class="primary" :disabled="busy">保存配置</button></div>
        </form>
      </section>
    </div>
  </main>
</template>
