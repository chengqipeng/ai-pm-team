# GitHub Repo Manager Skill

管理 GitHub 仓库的技能，支持创建仓库、推送代码、管理远程仓库等操作。

## 触发条件
当用户提到以下关键词时激活此技能：
- "创建GitHub仓库"、"推送到GitHub"、"上传到GitHub"
- "github repo"、"git push"、"创建远程仓库"

## 默认配置

- GitHub Owner: `chengqipeng`
- GitHub Token 环境变量: `GITHUB_TOKEN`（存储在 `tools/.env`）
- SSH Remote 格式: `git@github.com:chengqipeng/{repo-name}.git`

## 能力

### 1. 创建 GitHub 仓库
使用 GitHub REST API 通过 access token 创建仓库：

```bash
curl -s -X POST https://api.github.com/user/repos \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -d '{"name":"{repo-name}","description":"{description}","private":false}'
```

### 2. 初始化本地 Git 并推送
```bash
# 初始化（如果还不是 git 仓库）
git init
git add -A
git commit -m "Initial commit"

# 添加 SSH remote 并推送
git remote add origin git@github.com:chengqipeng/{repo-name}.git
git branch -M main
git push -u origin main
```

### 3. 日常提交推送
```bash
git add -A
git commit -m "{commit-message}"
git push
```

## 安全注意事项
- access token 存储在 `tools/.env` 中，已被 `.gitignore` 排除
- 推送使用 SSH key，无需在命令中暴露 token
- 创建仓库时从环境变量读取 token

## 使用流程

1. 读取 `tools/.env` 获取 `GITHUB_TOKEN` 和 `GITHUB_OWNER`
2. 使用 API 创建仓库（如需要）
3. 配置 SSH remote
4. 执行 git 操作（add、commit、push）

## 常用操作速查

| 操作 | 命令 |
|------|------|
| 创建仓库 | `curl -X POST https://api.github.com/user/repos -H "Authorization: token $GITHUB_TOKEN" -d '{"name":"repo-name"}'` |
| 添加远程 | `git remote add origin git@github.com:chengqipeng/repo-name.git` |
| 推送 | `git push -u origin main` |
| 查看远程 | `git remote -v` |
| 删除仓库 | `curl -X DELETE https://api.github.com/repos/chengqipeng/repo-name -H "Authorization: token $GITHUB_TOKEN"` |
