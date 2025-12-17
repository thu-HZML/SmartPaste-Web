# 1. 使用 Python 3.11 适配 Django 5
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 2. 修改系统源为阿里云 (加速 apt install)
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 3. 安装系统依赖
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 4. 【关键步骤】配置全局 pip 源为清华源
# 这样设置后，后续所有的 pip install 都不用手动加 -i 了
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 复制依赖文件
COPY requirements.txt /app/

# 6. 安装依赖 (增加超时时间防止波动)
RUN pip install --upgrade pip
RUN pip install --default-timeout=100 -r requirements.txt
RUN pip install gunicorn

# 7. 复制项目代码
COPY . /app/

# 8. 创建静态文件目录
RUN mkdir -p /app/static /app/media

EXPOSE 8000

# 9. 启动命令
CMD ["gunicorn", "app.wsgi:application", "--bind", "0.0.0.0:8000"]