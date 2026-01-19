# SmartPaste-Web

SmartPaste 的后端服务核心。这是一个基于 Django 和 Django REST Framework 构建的高效剪贴板同步与 AI 助手平台，旨在提供无缝的跨设备体验和智能化的内容处理。

## 📋 功能特性

### 🔄 跨设备同步 (Sync)
- **剪贴板历史云同步**：支持文本、富文本等数据的即时同步 (`ClipboardData`)。
- **文件传输**：支持图片、文档等文件的跨设备传输，采用 MD5 校验确保文件完整性与去重 (`ClipboardFile`)。
- **用户配置漫游**：统一管理用户偏好设置 (`UserConfig`)。

### 🧠 AI 智能助手 (AI Assistant)
- **剪贴板交互**：直接对剪贴板中的内容（文本、图片、文件）发起提问。
- **多模态支持**：支持解析和理解文本与图片内容。
- **流式响应**：基于 OpenAI 接口标准，支持打字机效果的流式回复体验。
- **灵活配置**：支持自定义 AI 提供商与模型参数。

### 🔐 安全与账户 (Accounts)
- **安全认证**：基于 JWT (JSON Web Token) 的无状态认证机制。
- **用户管理**：注册、登录、密码重置、头像管理。
- **数据隐私**：提供端对端加密密钥管理接口 (`EncryptionKeyView`)，保障用户数据安全。

## 🛠 技术栈

- **后端框架**: [Django 5.x](https://www.djangoproject.com/)
- **API 框架**: [Django REST Framework](https://www.django-rest-framework.org/)
- **数据库**: MySQL (生产推荐) / SQLite (默认开发)
- **认证**: JWT (`djangorestframework-simplejwt`)
- **AI 集成**: OpenAI SDK
- **部署**: Docker & Docker Compose

## 🚀 快速开始

### 环境准备

- Python 3.8+
- MySQL (可选，若不使用 SQLite)
- Git

### 📦 本地开发设置

1.  **克隆项目**

    ```bash
    git clone https://github.com/your-repo/SmartPaste-Web.git
    cd SmartPaste-Web/backend
    ```

2.  **创建并激活虚拟环境** (推荐)

    ```bash
    python -m venv venv
    # Windows:
    .\venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```

3.  **安装依赖**

    ```bash
    pip install -r requirements.txt
    ```

4.  **数据库迁移**

    初始化数据库表结构：

    ```bash
    python manage.py makemigrations
    python manage.py migrate
    ```

5.  **启动开发服务器**

    ```bash
    python manage.py runserver
    ```
    服务默认运行在 `http://127.0.0.1:8000`。

### 🐳 Docker 部署

确保已安装 [Docker](https://www.docker.com/) 和 Docker Compose。

```bash
cd backend
# 启动服务
docker-compose up -d
```

## 📂 核心目录结构

```text
backend/
├── accounts/       # 用户注册、登录与档案管理
├── ai_assistant/   # AI 对话、模型配置与处理视图
├── sync/           # 剪贴板数据同步、文件存储逻辑
├── app/            # 项目主配置 (Settings, URLs, WSGI, ASGI)
├── media/          # 用户上传文件存储目录
├── manage.py       # Django 命令行入口
└── requirements.txt
```

## 🔌 API 概览

| 模块 | 路径前缀 | 说明 |
| :--- | :--- | :--- |
| **认证** | `/api/accounts/` | `/login`, `/register`, `/profile`, `/encryption-keys/` |
| **同步** | `/api/sync/` | 剪贴板数据的 CRUD 及文件上传下载接口 |
| **AI** | `/api/ai/` | 智能问答接口，支持多模态输入 |

---

**SmartPaste** - Connect your clipboard, empower your workflow.
