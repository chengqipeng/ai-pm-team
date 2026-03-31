#!/bin/bash
# 一键提交并推送所有变更到远程仓库
# 用法: ./tools/git-push.sh [commit message]
# 如果不传 message，会自动生成一个带时间戳的默认消息

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 切到仓库根目录
cd "$(git rev-parse --show-toplevel)"

# 检查是否有变更
if [ -z "$(git status --porcelain)" ]; then
    echo -e "${YELLOW}没有需要提交的变更${NC}"
    exit 0
fi

# 显示变更
echo -e "${GREEN}=== 变更文件 ===${NC}"
git status --short
echo ""

# commit message
if [ -n "$1" ]; then
    MSG="$1"
else
    MSG="chore: 更新于 $(date '+%Y-%m-%d %H:%M:%S')"
fi

# 安全检查：确保 .env 文件不会被提交
git ls-files --cached | grep -i '\.env' | while read f; do
    echo -e "${RED}⚠️  检测到已跟踪的敏感文件: $f，正在移除...${NC}"
    git rm --cached "$f" 2>/dev/null
done

# 提交
git add -A
git commit -m "$MSG"

# 推送，失败则 rebase 重试
echo -e "${GREEN}=== 推送到远程 ===${NC}"
if ! git push 2>/dev/null; then
    echo -e "${YELLOW}推送失败，尝试 rebase...${NC}"
    if ! git pull --rebase; then
        echo -e "${RED}rebase 有冲突，请手动解决后重新运行${NC}"
        exit 1
    fi
    git push
fi

echo ""
echo -e "${GREEN}✅ 提交成功${NC}"
git log --oneline -1
