# 修复 GitHub Container Registry (GHCR) 推送权限问题

## 问题描述

当遇到以下错误时：
```
ERROR: failed to build: failed to solve: failed to push ghcr.io/raomaiping/flow2api:main: denied: permission_denied: write_package
```

这通常是因为 GitHub Actions 的 `GITHUB_TOKEN` 没有足够的权限推送到 GitHub Container Registry。

## 解决方案

### 1. 检查并更新仓库的 Actions 权限设置

1. 访问仓库设置页面：
   - 打开 `https://github.com/raomaiping/flow2api/settings`
   - 或者：仓库首页 → Settings → Actions → General

2. 找到 "Workflow permissions" 部分

3. 确保选择以下选项之一：
   - ✅ **Read and write permissions** (推荐)
   - 或者：**Read repository contents and packages permissions** + 在 workflow 文件中显式声明权限（已配置）

4. 如果选择了 "Read and write permissions"，确保勾选：
   - ✅ Allow GitHub Actions to create and approve pull requests

5. 点击 **Save** 保存设置

### 2. 关于包页面 404 错误

**重要：如果访问 `https://github.com/raomaiping/flow2api/pkgs/container/flow2api` 显示 404，这是正常的！**

包会在**第一次成功推送镜像后自动创建**。在此之前，包页面不存在是正常现象。

**首次推送后，包会自动创建，然后你可以：**

1. 访问包的设置页面：
   - 打开 `https://github.com/raomaiping/flow2api/pkgs/container/flow2api`
   - 或者：GitHub 首页 → 右上角头像 → Your profile → Packages → flow2api

2. 点击包名称进入包详情页

3. 点击右侧的 **Package settings**

4. 在 "Manage Actions access" 部分：
   - 确保 `raomaiping/flow2api` 仓库已添加
   - 权限设置为 **Write** 或 **Admin**

5. 如果没有添加，点击 **Add repository** 添加仓库并设置权限

**注意：** 首次推送时，如果仓库的 Actions 权限设置正确，包会自动创建并关联到仓库。

### 3. 验证 workflow 文件权限配置

**重要：如果仓库已设置 "Read and write permissions"，则不需要在 workflow 中显式声明权限！**

显式声明权限可能会覆盖仓库的默认权限设置，导致权限不足。

**推荐做法：**
- 如果仓库设置了 "Read and write permissions"：**移除 workflow 中的 `permissions` 声明**，让使用默认权限
- 如果仓库设置了 "Read repository contents and packages permissions"：需要在 workflow 中显式声明 `packages: write`

✅ 已更新 workflow 文件，移除了显式权限声明，使用仓库默认权限。

### 4. 如果问题仍然存在

如果完成上述步骤后问题仍然存在，可以尝试：

1. **使用 Personal Access Token (PAT)**：
   - 创建一个具有 `write:packages` 权限的 PAT
   - 在仓库 Settings → Secrets and variables → Actions 中添加名为 `GHCR_TOKEN` 的 secret
   - 在 workflow 文件中使用 `${{ secrets.GHCR_TOKEN }}` 替代 `${{ secrets.GITHUB_TOKEN }}`

2. **检查是否在正确的分支上运行**：
   - 确保 workflow 在默认分支（main/master）上运行
   - `GITHUB_TOKEN` 的权限可能只在默认分支上生效

3. **检查仓库是否为私有仓库**：
   - 私有仓库的包访问权限可能需要额外配置

## 验证修复

完成上述步骤后：

1. 推送代码到 main 分支
2. 查看 GitHub Actions 运行日志
3. 如果成功，可以在 `https://github.com/raomaiping/flow2api/pkgs/container/flow2api` 看到新推送的镜像

## 参考链接

- [GitHub Actions 权限文档](https://docs.github.com/en/actions/security-guides/automatic-token-authentication#permissions-for-the-github_token)
- [GitHub Container Registry 文档](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [修复 403 Forbidden GHCR 问题](https://hackmd.io/@maelvls/fixing-403-forbidden-ghcr)
