# AI Shared Serial Gateway

一个面向人工与 AI Agent 的多串口共享网关。每个硬件串口拥有独立的 Telnet 端口，同时支持网页终端、REST API、实时日志与在线修改串口参数。

## 当前雏形

- Vue 3 登录页、管理控制台和实时串口终端
- FastAPI 单用户 Cookie 会话认证
- 多串口通道；每条通道可配置名称、设备、波特率、数据位、校验位、停止位和 Telnet 端口
- SecureCRT Telnet 基础协商兼容
- WebSocket 实时广播 UART、网页、Telnet 和 AI 操作
- 模拟串口模式，无硬件也能演示
- 配置和日志持久化到 `data/`

> 这是内部网络雏形。正式暴露到不可信网络前，应在前面部署 HTTPS 反向代理，并增加登录限速、CSRF 防护和更完善的用户权限。

生产环境由 FastAPI 提供已构建的 `frontend/dist` 静态文件，不运行或暴露 Vite 开发服务器。

## 本地启动

```bash
cd /home/muskr/code/serial-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
SERIAL_GATEWAY_SECRET="$(openssl rand -hex 32)" .venv/bin/python -m serial_gateway
```

打开 `http://主机IP:8000`。雏形默认账号为 `admin / admin123`，部署时必须通过环境变量修改。

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

首次启动会生成 `data/config.json`。日常配置通过网页完成，无需手工修改。真实部署时关闭对应通道的“模拟串口”开关。
