# AI Shared Serial Gateway

一个面向人工与 AI Agent 的多串口共享网关。每个硬件串口拥有独立的 Telnet 端口，同时支持网页终端、REST API、实时日志与在线修改串口参数。

## 当前雏形

- Vue 3 登录页、通道管理和 xterm 交互式串口终端
- FastAPI 单用户 Cookie 会话认证
- 多串口通道；每条通道可配置名称、设备、波特率、数据位、校验位、停止位和 Telnet 端口
- SecureCRT Telnet 基础协商兼容
- WebSocket 逐键双向传输，支持 Tab 补全、方向键、Ctrl+C 和 ANSI 颜色
- 网页终端与 SecureCRT 共享同一串口，终端数据保持透明、不插入额外标记
- 配置和日志持久化到 `data/`

> 这是内部网络雏形。正式暴露到不可信网络前，应在前面部署 HTTPS 反向代理，并增加登录限速、CSRF 防护和更完善的用户权限。

生产环境由 FastAPI 提供已构建的 `frontend/dist` 静态文件，不运行或暴露 Vite 开发服务器。

## 编译与运行

### 系统要求

- Linux
- Python 3.11 或以上版本，推荐 Python 3.12
- Node.js 18 或以上版本
- npm

检查版本：

```bash
python3 --version
node --version
npm --version
```

### 获取源码

```bash
git clone git@github.com:ALiceSKR/serial-gateway.git
cd serial-gateway
```

### 编译前端

Vue 前端需要通过 Vite 构建：

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

构建产物位于 `frontend/dist/`。生产运行时由 FastAPI 直接提供这些静态文件，不需要启动 Vite 开发服务器。

### 安装后端

Python 后端不需要编译，创建虚拟环境并安装依赖即可：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 串口权限

运行用户必须属于 `dialout` 组，才能访问 `/dev/ttyUSB*`：

```bash
sudo usermod -aG dialout "$USER"
```

执行后需要退出系统并重新登录，新的用户组权限才会生效。systemd 部署应使用专用系统用户，并在服务中配置 `Group=dialout` 和 `SupplementaryGroups=dialout`。

### 启动

```bash
export SERIAL_GATEWAY_USERNAME=admin
export SERIAL_GATEWAY_PASSWORD='替换为强密码'
export SERIAL_GATEWAY_SECRET="$(openssl rand -hex 32)"

.venv/bin/python -m serial_gateway
```

打开 `http://主机IP:8000`。Web 服务默认监听 `8000`，第一条串口通道的 Telnet 端口默认为 `2000`。

`SERIAL_GATEWAY_SECRET` 用于签名登录会话 Cookie。正式部署时生成一次后固定保存，不要在每次启动时重新生成，也不要提交到 Git。

SecureCRT 使用 Telnet 协议，连接每条通道在网页中设置的端口（默认第一条为 `2000`）。

## AI API

当前 API 与网页共用登录 Cookie。先登录并保存 Cookie：

```bash
curl -c cookie.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  http://115机器IP:8000/api/login

curl -b cookie.txt -H 'Content-Type: application/json' \
  -d '{"port_id":"uart0","data":"printenv\n","source":"AI"}' \
  http://115机器IP:8000/api/send
```

## 部署到 115 机器

1. 构建前端后，将整个项目复制到 `/opt/serial-gateway`。
2. 创建系统用户并加入 `dialout` 组，确保有权访问 `/dev/ttyUSB*`。
3. 创建 `/var/lib/serial-gateway`，所有者设为 `serial-gateway:dialout`。
4. 将 `deploy/serial-gateway.service` 安装到 `/etc/systemd/system/`。
5. 创建 `/etc/serial-gateway.env`：

```ini
SERIAL_GATEWAY_USERNAME=admin
SERIAL_GATEWAY_PASSWORD=替换为强密码
SERIAL_GATEWAY_SECRET=替换为至少32字节的随机字符串
```

6. 执行 `systemctl daemon-reload && systemctl enable --now serial-gateway`。
7. 只在可信管理网开放 TCP `8000`，并开放网页中实际配置的 Telnet 端口（如 `2000-2010`）。

## 配置文件

首次启动会生成 `data/config.json`。日常配置通过网页完成，无需手工修改。生产环境可通过 `SERIAL_GATEWAY_DATA` 指定持久化目录，例如 `/var/lib/serial-gateway`。
