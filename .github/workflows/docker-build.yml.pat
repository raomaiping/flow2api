name: Build and Push Docker Image (使用 PAT)

# 如果使用 GITHUB_TOKEN 仍然失败，可以使用此版本（需要配置 GHCR_TOKEN secret）
# 使用方法：
# 1. 创建 Personal Access Token (PAT) with write:packages permission
# 2. 在仓库 Settings → Secrets → Actions 中添加 GHCR_TOKEN
# 3. 将此文件内容替换到 docker-build.yml

on:
  push:
    branches:
      - main
      - master
    tags:
      - 'v*'
    paths:
      - 'src/**'
      - 'main.py'
      - 'Dockerfile'
      - 'requirements.txt'
      - 'config/**'
      - 'static/**'
      - '.github/workflows/docker-build.yml'
      - '!recaptcha_service.py'
      - '!Dockerfile.recaptcha-service'
      - '!requirements-recaptcha-service.txt'
      - '!.github/workflows/recaptcha-service-deploy.yml'
  pull_request:
    branches:
      - main
      - master
    paths:
      - 'src/**'
      - 'main.py'
      - 'Dockerfile'
      - 'requirements.txt'
      - 'config/**'
      - 'static/**'
      - '.github/workflows/docker-build.yml'
      - '!recaptcha_service.py'
      - '!Dockerfile.recaptcha-service'
      - '!requirements-recaptcha-service.txt'
      - '!.github/workflows/recaptcha-service-deploy.yml'

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GitHub Container Registry
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GHCR_TOKEN }}

      - name: Extract metadata (tags, labels) for Docker
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./Dockerfile
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64,linux/arm64

      - name: Image digest
        run: echo ${{ steps.meta.outputs.digest }}
