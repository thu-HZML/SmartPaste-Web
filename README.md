

### 第一步：环境准备与项目创建

在你的终端（命令行）中执行以下命令：

```bash
# 1. 创建虚拟环境 (可选，但推荐)
python -m venv venv
# Windows 激活: venv\Scripts\activate
# Mac/Linux 激活: source venv/bin/activate

# 2. 安装 Django 和 Django REST Framework
pip install django djangorestframework

# 或者直接从 requirements.txt 安装依赖
pip install -r requirements.txt

```



### 第二步：本地运行服务器

在打包 Docker 之前，先确认代码是通的。

1.  **docker-compose**：
    ```bash
    docker-compose up -d
    ```
    
2.  **生成数据库表**：
    ```bash
    python manage.py makemigrations
    python manage.py migrate
    ```

3.  **启动服务**：
    ```bash
    python manage.py runserver
    ```
