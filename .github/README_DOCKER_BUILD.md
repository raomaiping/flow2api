# Docker 自动构建说明

## 功能

当代码推送到 `main` 或 `master` 分支时，GitHub Actions 会自动：
1. 构建 Docker 镜像
2. 推送到 GitHub Container Registry (ghcr.io/raomaiping/flow2api)

## 设置步骤

**无需额外配置！**

使用 GitHub Container Registry (ghcr.io) 的好处：
- ✅ 无需配置 Docker Hub credentials
- ✅ 自动使用 `GITHUB_TOKEN`（GitHub Actions 自动提供）
- ✅ 与 GitHub 仓库紧密集成
- ✅ 免费使用

### 3. 工作流触发

- **Push 到 main/master 分支**: 自动构建并推送镜像
- **创建 Tag (v*格式)**: 构建并推送带版本标签的镜像
- **Pull Request**: 仅构建镜像（不推送），用于验证

### 4. 镜像标签

- `latest`: main/master 分支的最新版本
- `main`: main 分支的镜像
- `v1.0.0`: 语义化版本标签（如果创建了对应的 git tag）
- `v1.0`, `v1`: 版本别名

## 使用

推送代码后，可以在以下位置查看构建状态：
- GitHub Actions 页面: `https://github.com/raomaiping/flow2api/actions`
- GitHub Container Registry: `https://github.com/raomaiping/flow2api/pkgs/container/flow2api`

构建完成后，可以使用以下命令拉取镜像：

```bash
docker pull ghcr.io/raomaiping/flow2api:latest
```

或使用 docker-compose：

```bash
docker-compose pull
docker-compose up -d
```

