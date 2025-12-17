# reCAPTCHA Token Service - 自动部署指南

## 概述

reCAPTCHA Token Service 已配置为自动构建和部署 Docker 镜像到 Docker Hub。

## 触发条件

自动构建在以下情况触发：

1. **推送到 main/master 分支**
   - 当以下文件被修改时：
     - `recaptcha_service.py`
     - `Dockerfile.recaptcha-service`
     - `src/services/self_recaptcha_solver.py`
     - `.github/workflows/recaptcha-service-deploy.yml`

2. **Pull Request**
   - 提交到 main/master 分支的 PR（仅构建，不推送）

3. **手动触发**
   - 通过 GitHub Actions 界面手动触发
   - 可以指定自定义 tag

## Docker 镜像

### 镜像信息

- **Registry**: `ghcr.io` (GitHub Container Registry)
- **Image Name**: `YOUR_USERNAME/flow2api/flow2api-recaptcha-service`
- **完整镜像名**: `ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest`
- **说明**: `YOUR_USERNAME` 会自动使用 GitHub 仓库的所有者

### 标签规则

- `latest` - 默认分支（main/master）的最新版本
- `main` / `master` - 分支名
- `v1.0.0` - 语义化版本标签
- `v1.0` - 主版本.次版本
- `v1` - 主版本

## 使用 Docker 镜像

### 拉取镜像

```bash
docker pull ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
```

### 运行容器

```bash
docker run -d \
  --name recaptcha-service \
  -p 8001:8001 \
  --shm-size=2gb \
  -e PLAYWRIGHT_HEADLESS=true \
  -e RECAPTCHA_SERVICE_PORT=8001 \
  ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
```

### 使用 docker-compose

```yaml
version: '3.8'

services:
  recaptcha-service:
    image: ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
    ports:
      - "8001:8001"
    environment:
      - PLAYWRIGHT_HEADLESS=true
      - RECAPTCHA_SERVICE_PORT=8001
    shm_size: 2gb
    mem_limit: 2g
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

## GitHub Secrets 配置

**无需额外配置！**

使用 GitHub Container Registry (ghcr.io) 的好处：
- ✅ 无需配置 Docker Hub credentials
- ✅ 自动使用 `GITHUB_TOKEN`（GitHub Actions 自动提供）
- ✅ 与 GitHub 仓库紧密集成
- ✅ 免费使用

## 本地构建测试

### 构建镜像

```bash
docker build -f Dockerfile.recaptcha-service -t flow2api-recaptcha-service:test .
```

### 运行测试

```bash
docker run -d \
  --name recaptcha-service-test \
  -p 8001:8001 \
  --shm-size=2gb \
  flow2api-recaptcha-service:test
```

### 测试服务

```bash
curl http://localhost:8001/health
```

## 多架构支持

Docker 镜像支持以下架构：

- `linux/amd64` - x86_64
- `linux/arm64` - ARM64

## 部署到生产环境

### 1. 使用 Docker

```bash
docker run -d \
  --name recaptcha-service \
  -p 8001:8001 \
  --shm-size=2gb \
  --restart unless-stopped \
  -e PLAYWRIGHT_HEADLESS=true \
  -e RECAPTCHA_SERVICE_PORT=8001 \
  ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
```

### 2. 使用 Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  recaptcha-service:
    image: ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
    ports:
      - "8001:8001"
    environment:
      - PLAYWRIGHT_HEADLESS=true
      - RECAPTCHA_SERVICE_PORT=8001
    shm_size: 2gb
    mem_limit: 2g
    restart: unless-stopped
```

运行：

```bash
docker-compose up -d
```

### 3. 使用 Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: recaptcha-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: recaptcha-service
  template:
    metadata:
      labels:
        app: recaptcha-service
    spec:
      containers:
      - name: recaptcha-service
        image: ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
        ports:
        - containerPort: 8001
        env:
        - name: PLAYWRIGHT_HEADLESS
          value: "true"
        - name: RECAPTCHA_SERVICE_PORT
          value: "8001"
        resources:
          requests:
            memory: "1Gi"
          limits:
            memory: "2Gi"
        volumeMounts:
        - name: dshm
          mountPath: /dev/shm
      volumes:
      - name: dshm
        emptyDir:
          medium: Memory
          sizeLimit: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: recaptcha-service
spec:
  selector:
    app: recaptcha-service
  ports:
  - port: 8001
    targetPort: 8001
  type: ClusterIP
```

## 监控和日志

### 查看日志

```bash
docker logs recaptcha-service
docker logs -f recaptcha-service  # 实时日志
```

### 健康检查

```bash
curl http://localhost:8001/health
```

### 检查容器状态

```bash
docker ps | grep recaptcha-service
docker inspect recaptcha-service
```

## 版本管理

### 创建新版本

1. 创建带版本号的 tag：

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

2. GitHub Actions 会自动构建并推送带版本标签的镜像

### 回滚到旧版本

```bash
docker pull ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:v1.0.0
docker stop recaptcha-service
docker rm recaptcha-service
docker run -d \
  --name recaptcha-service \
  -p 8001:8001 \
  --shm-size=2gb \
  ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:v1.0.0
```

## 故障排查

### 镜像构建失败

1. 检查 GitHub Actions 日志
2. 确认 Docker Hub secrets 配置正确
3. 检查 Dockerfile 语法

### 容器启动失败

1. 检查日志：`docker logs recaptcha-service`
2. 确认端口没有被占用
3. 检查内存是否足够（至少 2GB）

### 服务无响应

1. 检查健康状态：`curl http://localhost:8001/health`
2. 查看容器日志
3. 确认浏览器初始化成功

## 更新服务

### 自动更新

当代码推送到 main/master 分支时，会自动构建新镜像。

### 手动更新

```bash
docker pull ghcr.io/YOUR_USERNAME/flow2api/flow2api-recaptcha-service:latest
docker stop recaptcha-service
docker rm recaptcha-service
# 使用新的运行命令启动
```

## 相关文档

- [reCAPTCHA Service README](RECAPTCHA_SERVICE_README.md)
- [快速开始指南](RECAPTCHA_SERVICE_QUICKSTART.md)
- [测试结果](RECAPTCHA_SERVICE_TEST_RESULTS.md)

