---
name: git-commit-push
slug: git-commit-push
version: 1.0.0
description: 提交代码变更并推送到 GitHub，自动生成 commit message、处理冲突和子模块。
---

# Git Commit & Push

将本地代码变更提交并推送到 GitHub 远程仓库。

## When to Use
- 用户说"提交代码"、"推送到GitHub"、"commit"、"push"、"提交变更"
- 用户完成一组修改后要求同步到远程

## Core Rules

1. 提交前必须先 `git status` 查看变更范围，向用户确认提交内容
2. commit message 使用 Conventional Commits 格式（中文描述），如 `feat: 重写产品上下文为元数据体系`
3. 如果工作区包含子模块（repos/ 下的 git 仓库），只提交当前仓库的变更，不进入子模块
4. push 失败时先 `git pull --rebase` 再重试，有冲突则停下来告知用户
5. 敏感文件（.env、token、密码）不得提交，提交前检查 `.gitignore`

## Workflow

```
1. git status                          # 查看变更
2. 向用户确认提交范围和 commit message
3. git add {files}                     # 按用户确认的范围添加（默认 -A）
4. git commit -m "{message}"           # 提交
5. git push                            # 推送
6. 如果 push 失败 → git pull --rebase → git push
7. 报告结果（commit hash + 推送状态）
```

## Commit Message 规范

| 前缀 | 用途 | 示例 |
|------|------|------|
| feat | 新功能/新文件 | `feat: 新增元数据体系 PRD` |
| fix | 修复 | `fix: 修复 db_column 映射规则描述` |
| refactor | 重构（不改行为） | `refactor: steering 模板通用化，移除产品硬编码` |
| docs | 文档 | `docs: 更新 README 工作流说明` |
| chore | 杂项（配置/脚本） | `chore: 更新 .gitignore` |

多类变更时用最主要的前缀，body 中列出其他变更。

## Git Config

- Remote: 从 `git remote -v` 读取，不硬编码
- Branch: 从 `git branch --show-current` 读取
- 子模块目录（repos/）：检查 `.gitmodules` 或 repos/ 下的 `.git` 目录，避免误操作

## Error Handling

| 场景 | 处理 |
|------|------|
| nothing to commit | 告知用户无变更 |
| push rejected (non-fast-forward) | `git pull --rebase` 后重试 |
| rebase conflict | 停止，列出冲突文件，等用户处理 |
| remote not configured | 提示用户配置 remote 或使用 `#github-repo-manager` |
| 大文件 (>50MB) | 警告用户，建议 .gitignore |