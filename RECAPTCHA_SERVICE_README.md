# reCAPTCHA Token Service

独立的 HTTP 服务，用于获取 reCAPTCHA v3 token。该服务保持浏览器持续运行，复用浏览器实例以提高性能。

## 📚 相关文档

- [部署指南](RECAPTCHA_SERVICE_DEPLOY.md) - 详细部署说明和GitHub Actions配置
- [测试结果](tests/results/RECAPTCHA_SERVICE_TEST_RESULTS.md) - 服务测试结果

## 特性

- ✅ **高性能**: 复用浏览器实例，避免每次请求都启动浏览器
- ✅ **低延迟**: 浏览器已预启动，token 获取速度更快
- ✅ **独立服务**: 可以作为独立服务运行，也可以集成到主应用
- ✅ **并发支持**: 使用浏览器上下文隔离，支持并发请求
- ✅ **自动恢复**: 如果浏览器崩溃，会自动重新初始化

## 性能对比

| 方式 | 首次请求耗时 | 后续请求耗时 | 内存占用 |
|------|-------------|-------------|---------|
| 每次启动浏览器 | ~8-12 秒 | ~8-12 秒 | ~500MB-1GB（每次） |
| **本服务（复用浏览器）** | **~5-8 秒** | **~2-5 秒** | **~500MB-1GB（持续）** |

## 安装依赖

```bash
# 安装 Playwright（如果还未安装）
pip install playwright
playwright install chromium
```

## 运行服务

### 方式1: 直接运行

```bash
python recaptcha_service.py
```

服务将在 `http://0.0.0.0:8001` 启动。

### 方式2: 使用环境变量配置

```bash
# 设置端口（默认 8001）
export RECAPTCHA_SERVICE_PORT=8001

# 设置主机（默认 0.0.0.0）
export RECAPTCHA_SERVICE_HOST=0.0.0.0

# 设置无头模式（Docker 环境）
export PLAYWRIGHT_HEADLESS=true

python recaptcha_service.py
```

### 方式3: 使用 uvicorn 运行

```bash
uvicorn recaptcha_service:app --host 0.0.0.0 --port 8001
```

## API 文档

启动服务后，访问 `http://localhost:8001/docs` 查看交互式 API 文档。

## API 端点

### 1. 获取 Token

**POST** `/token`

**请求体**:
```json
{
  "project_id": "your-project-id"
}
```

**响应** (成功):
```json
{
  "success": true,
  "token": "03AGdBq24T...",
  "duration_ms": 2345.67
}
```

**响应** (失败):
```json
{
  "success": false,
  "token": null,
  "duration_ms": 1234.56,
  "error": "Failed to get token"
}
```

### 2. 健康检查

**GET** `/health`

**响应**:
```json
{
  "status": "healthy",
  "browser_initialized": true,
  "headless": false
}
```

### 3. 根路径

**GET** `/`

返回服务信息和可用端点列表。

## 使用示例

### Python 示例

```python
import requests

# 获取 token
response = requests.post(
    "http://localhost:8001/token",
    json={"project_id": "your-project-id"}
)

data = response.json()
if data["success"]:
    token = data["token"]
    print(f"Token: {token}")
    print(f"耗时: {data['duration_ms']:.0f}ms")
else:
    print(f"错误: {data['error']}")
```

### cURL 示例

```bash
curl -X POST "http://localhost:8001/token" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

### JavaScript/Node.js 示例

```javascript
const response = await fetch('http://localhost:8001/token', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    project_id: 'your-project-id'
  })
});

const data = await response.json();
if (data.success) {
  console.log('Token:', data.token);
  console.log('耗时:', data.duration_ms, 'ms');
} else {
  console.error('错误:', data.error);
}
```

## 集成到主应用

### 方式1: 修改 `flow_client.py` 使用服务

```python
async def _get_recaptcha_token_via_service(self, project_id: str) -> Optional[str]:
    """通过独立的 reCAPTCHA 服务获取 token"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://localhost:8001/token",
                json={"project_id": project_id}
            )
            data = response.json()
            if data.get("success") and data.get("token"):
                return data["token"]
    except Exception as e:
        debug_logger.log_error(f"[reCAPTCHA] 服务调用失败: {str(e)}")
    return None
```

### 方式2: 在同一进程中运行（共享浏览器实例）

修改 `src/services/self_recaptcha_solver.py`，使用全局单例模式。

## Docker 部署

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install playwright && \
    playwright install chromium

# 复制项目文件
COPY . .

# 设置环境变量
ENV PLAYWRIGHT_HEADLESS=true
ENV RECAPTCHA_SERVICE_PORT=8001

EXPOSE 8001

CMD ["python", "recaptcha_service.py"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  recaptcha-service:
    build: .
    ports:
      - "8001:8001"
    environment:
      - PLAYWRIGHT_HEADLESS=true
      - RECAPTCHA_SERVICE_PORT=8001
    shm_size: 2gb
    mem_limit: 2g
```

## 性能优化建议

1. **预热服务**: 服务启动后，可以发送一个测试请求来预热浏览器
2. **连接池**: 如果使用 HTTP 客户端，建议使用连接池
3. **超时设置**: 根据实际情况调整超时时间（默认 30 秒）
4. **监控**: 监控服务的健康状态和性能指标

## 故障排查

### 浏览器启动失败

- 检查是否安装了 Chromium: `playwright install chromium`
- 检查系统依赖是否完整（Linux 需要安装相关库）
- 检查内存是否足够（建议至少 2GB）

### Token 获取失败

- 检查 `project_id` 是否正确
- 检查网络连接是否正常
- 查看服务日志了解详细错误信息

### 服务无响应

- 检查服务是否正常运行: `curl http://localhost:8001/health`
- 检查端口是否被占用
- 查看服务日志

## 注意事项

1. **内存占用**: 服务会持续占用 ~500MB-1GB 内存（浏览器常驻）
2. **并发限制**: 虽然支持并发，但建议限制并发数量（例如最多 10 个并发请求）
3. **稳定性**: 如果长时间运行，建议定期重启服务（例如每天重启一次）
4. **监控**: 建议添加监控和告警，确保服务正常运行

## yescaptcha 配置（替代方案）

本项目也支持使用 yescaptcha 平台获取 reCAPTCHA token。

### 配置方法

1. 访问 [yescaptcha.com](https://yescaptcha.com/) 注册账户并获取 API Key
2. 编辑 `config/setting.toml`：
   ```toml
   [yescaptcha]
   enabled = true
   client_key = "your_api_key_here"
   ```
3. 在 `flow_client.py` 中，yescaptcha 会作为备用方案（当自实现服务失败时使用）

### 与 yescaptcha 对比

| 特性 | 本服务 | yescaptcha |
|------|--------|-----------|
| 成本 | 免费（只需服务器资源） | 付费（按次收费） |
| 性能 | 2-5 秒（复用浏览器） | 3-10 秒 |
| 稳定性 | 需要维护浏览器环境 | 由第三方维护 |
| 隐私 | 完全本地处理 | 数据经过第三方 |
| 部署复杂度 | 中等（需要浏览器环境） | 低（只需 API key） |

## 许可证

与主项目相同。

