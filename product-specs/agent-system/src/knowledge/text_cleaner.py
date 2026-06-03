"""文本清洗工具 — 去除影响向量化和 BM25 检索质量的噪声字符

典型噪声类型：
- LaTeX 数学公式标记：${}^{TM}$, \frac{1}{2}, \alpha 等
- 图片路径/引用：images/e382f1602d53830dd6f3f681e736bedb, ![alt](path)
- HTML 标签残留：<br>, <div class="...">
- Markdown 格式噪声：过多的 # * _ 等
- UUID / hash 字符串：a1b2c3d4e5f6...
- Base64 编码片段
- URL 路径（保留域名和关键路径词）
- 特殊符号堆积：™ ® © 的各种编码形式
- 连续重复字符/无意义分隔符

设计原则：
- 宁可少清不可过清 — 保留有语义价值的文本
- 清洗后文本用于 embedding 和 BM25，不影响用户展示（原文存 content 字段）
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 预编译正则表达式
# ═══════════════════════════════════════════════════════════

# LaTeX 公式（行内 $...$ 和块级 $$...$$）
_RE_LATEX_BLOCK = re.compile(r'\$\$[\s\S]*?\$\$')
_RE_LATEX_INLINE = re.compile(r'\$[^$\n]{1,200}\$')
# LaTeX 命令（\command{...} 或 \command[...]{...}）
_RE_LATEX_CMD = re.compile(r'\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*')

# 图片路径（markdown 图片语法 + 裸路径）
_RE_MD_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
_RE_IMAGE_PATH = re.compile(
    r'(?:images|img|assets|figures|pics?|photos?|media)/'
    r'[a-f0-9]{8,}(?:[._-][a-f0-9]+)*(?:\.\w{2,5})?',
    re.IGNORECASE,
)

# HTML 标签
_RE_HTML_TAG = re.compile(r'</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?\s*/?>')
# HTML 实体
_RE_HTML_ENTITY = re.compile(r'&(?:#\d{1,5}|#x[a-fA-F0-9]{1,4}|[a-zA-Z]{2,8});')

# URL（完整 URL）
_RE_URL = re.compile(
    r'https?://[^\s<>\"\'\)]{10,}',
    re.IGNORECASE,
)

# UUID / 长 hash 字符串（>=16 位十六进制）
_RE_HASH = re.compile(r'\b[a-f0-9]{16,}\b', re.IGNORECASE)
# 短 hash（8-15 位，但需要是独立 token，避免误伤正常数字）
_RE_SHORT_HASH = re.compile(r'\b[a-f0-9]{8,15}\b(?![a-zA-Z\u4e00-\u9fff])', re.IGNORECASE)

# Base64 片段（>=32 字符的 base64 字符串）
_RE_BASE64 = re.compile(r'[A-Za-z0-9+/]{32,}={0,2}')

# 文件路径（通用路径格式，含 hash 文件名的长路径）
_RE_FILE_PATH = re.compile(
    r'(?:[a-zA-Z]:\\|/)?(?:[\w.-]+[/\\]){3,}[\w.-]+\.\w{1,5}',
)

# Markdown 过度格式
_RE_MD_HEADER_NOISE = re.compile(r'^#{4,}\s*', re.MULTILINE)  # 4级以上标题的 # 号
_RE_MD_HR = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)  # 分隔线

# 连续重复的标点/符号（3个以上相同字符）
_RE_REPEATED_PUNCT = re.compile(r'([^\w\s\u4e00-\u9fff])\1{2,}')

# 多余空白
_RE_MULTI_NEWLINE = re.compile(r'\n{3,}')
_RE_MULTI_SPACE = re.compile(r'[ \t]{3,}')

# 特殊商标/版权符号的 LaTeX 编码形式
_RE_TRADEMARK_LATEX = re.compile(
    r'\$?\{?\}?\^?\{?(?:TM|tm|SM|sm|R|C)\}?\$?',
)

# 表格分隔符残留（markdown 表格的 |---|---|）
_RE_TABLE_SEP = re.compile(r'\|[\s:_-]+\|(?:[\s:_-]+\|)*')

# ── [新增] LKEAP OCR 乱码模式 ──

# 模式 1: 连续的 \mathrm{X} 序列（LKEAP 把每个字符都包在 \mathrm{} 中）
# 例: \mathrm{T}\mathrm{6}\mathrm{.}\mathrm{T}
# 注意: LKEAP 输出的 markdown 中 backslash 被转义为 \\mathrm
# 处理策略: 提取花括号内的文本拼接
_RE_MATHRM_CHAIN = re.compile(
    r'(?:\\{1,2}mathrm\{[^}]*\}\s*){3,}',  # 3个以上连续的 \mathrm{...} 或 \\mathrm{...}
)

# 模式 2: 深度嵌套的 \mathrm{~mathrm{~mathrm{...}}} 递归垃圾
# 例: \mathrm{~mathrm{~mathrm{c}}\mathrm{~mathrm{~mathrm{a}}}
_RE_MATHRM_NESTED = re.compile(
    r'\\{0,2}mathrm\{~?mathrm\{[^}]*\}[^}]*\}',
)

# 模式 3: 重复的 \mathrm{~{}} 空白占位（LKEAP 用来模拟空格/缩进）
_RE_MATHRM_SPACE = re.compile(
    r'(?:\\{1,2}mathrm\{~?\{?\}?\}\s*){2,}',
)

# 模式 4: LaTeX 表格对齐残留 — 连续的 & 和 \\ 组合
# 例: &&&&\\ &&&&&&&&&\\ &&&&&&&&&\\
_RE_LATEX_TABLE_ALIGN = re.compile(
    r'(?:[&\s]*\\\\[&\s]*){2,}',  # 两个以上 \\ 被 & 和空格包围
)
_RE_AMPERSAND_JUNK = re.compile(
    r'&(?:\s*&){2,}',  # 3个以上连续的 &（含空格）
)

# 模式 5: \text{X} 单字符包裹链（类似 \mathrm 的变体）
_RE_TEXT_CHAIN = re.compile(
    r'(?:\\{1,2}text\{[^}]*\}\s*){3,}',
)


# ═══════════════════════════════════════════════════════════
# 核心清洗函数
# ═══════════════════════════════════════════════════════════

def clean_text_for_retrieval(text: str) -> str:
    """清洗文本，去除影响向量化和 BM25 检索的噪声字符。

    Args:
        text: 原始切片文本

    Returns:
        清洗后的纯净文本，适合用于 embedding 和 BM25 索引

    设计原则：
    - 去除无语义价值的噪声（公式标记、hash、图片路径等）
    - 保留有意义的自然语言文本
    - 不改变语义内容的顺序和结构
    - 对于 LaTeX 公式，尝试提取其中的可读文本
    """
    if not text:
        return ""

    result = text

    # 1. 去除 LaTeX 块级公式（替换为空格，避免前后文黏连）
    result = _RE_LATEX_BLOCK.sub(' ', result)

    # 2. 去除 LaTeX 行内公式（尝试提取文本部分）
    result = _RE_LATEX_INLINE.sub(_replace_inline_latex, result)

    # 2.5 [新增] 清理 LKEAP OCR 产生的 LaTeX 乱码模式
    # 必须在通用 LaTeX 命令清理之前处理，因为这些模式需要特殊提取逻辑
    result = _RE_MATHRM_NESTED.sub(' ', result)       # 先清深度嵌套
    result = _RE_MATHRM_SPACE.sub(' ', result)        # 再清空白占位
    result = _RE_MATHRM_CHAIN.sub(_replace_mathrm_chain, result)  # 提取有效字符
    result = _RE_TEXT_CHAIN.sub(_replace_text_chain, result)       # \text{} 链
    result = _RE_LATEX_TABLE_ALIGN.sub(' ', result)   # 表格对齐残留
    result = _RE_AMPERSAND_JUNK.sub(' ', result)      # 连续 &

    # 3. 去除 LaTeX 命令
    result = _RE_LATEX_CMD.sub(' ', result)

    # 4. 去除 Markdown 图片
    result = _RE_MD_IMAGE.sub(' ', result)

    # 5. 去除图片路径
    result = _RE_IMAGE_PATH.sub(' ', result)

    # 6. 去除 HTML 标签
    result = _RE_HTML_TAG.sub(' ', result)

    # 7. 替换 HTML 实体为空格
    result = _RE_HTML_ENTITY.sub(' ', result)

    # 8. 去除 URL（保留域名关键词）
    result = _RE_URL.sub(_replace_url, result)

    # 9. 去除过长的文件路径（在 hash 之前，避免 hash 破坏路径结构）
    result = _RE_FILE_PATH.sub(_replace_filepath, result)

    # 10. 去除 Base64
    result = _RE_BASE64.sub(' ', result)

    # 11. 去除长 hash 字符串
    result = _RE_HASH.sub(' ', result)

    # 12. 去除短 hash（较保守）
    result = _RE_SHORT_HASH.sub(' ', result)

    # 13. 清理 Markdown 格式噪声
    result = _RE_MD_HEADER_NOISE.sub('', result)
    result = _RE_MD_HR.sub(' ', result)
    result = _RE_TABLE_SEP.sub(' ', result)

    # 14. 清理重复标点
    result = _RE_REPEATED_PUNCT.sub(r'\1', result)

    # 15. 清理商标 LaTeX 编码残留
    result = _RE_TRADEMARK_LATEX.sub(' ', result)

    # 16. 规范化空白
    result = _RE_MULTI_NEWLINE.sub('\n\n', result)
    result = _RE_MULTI_SPACE.sub(' ', result)

    # 17. 去除首尾空白
    result = result.strip()

    # 安全检查：如果清洗后过短（丢失了太多内容），返回简单清洗版本
    # 例外：如果原文中 LaTeX 命令占比超过 50%，说明原文本身就是乱码，
    # 激进清洗是正确的，不应 fallback
    latex_cmd_count = len(re.findall(r'\\{1,2}[a-zA-Z]+\{', text))
    is_latex_garbage = latex_cmd_count > len(text) / 20  # 平均每 20 字符有 1+ 个 \cmd{
    if len(result) < len(text) * 0.15 and len(text) > 50 and not is_latex_garbage:
        logger.debug(
            "Text cleaning too aggressive: original=%d cleaned=%d, using light clean",
            len(text), len(result),
        )
        return _light_clean(text)

    return result


def _light_clean(text: str) -> str:
    """轻度清洗 — 仅去除最明显的噪声，作为 fallback"""
    result = text
    result = _RE_LATEX_BLOCK.sub(' ', result)
    result = _RE_MD_IMAGE.sub(' ', result)
    result = _RE_HTML_TAG.sub(' ', result)
    result = _RE_URL.sub(' ', result)
    result = _RE_BASE64.sub(' ', result)
    result = _RE_HASH.sub(' ', result)
    result = _RE_MULTI_NEWLINE.sub('\n\n', result)
    result = _RE_MULTI_SPACE.sub(' ', result)
    return result.strip()


# ═══════════════════════════════════════════════════════════
# 替换辅助函数
# ═══════════════════════════════════════════════════════════

def _replace_inline_latex(match: re.Match) -> str:
    """尝试从行内 LaTeX 中提取可读文本。

    例如：${}^{TM}$ → TM
          $x = 5$ → x = 5
          $\\alpha$ → ''（纯命令，无可读文本）
    """
    content = match.group(0)[1:-1]  # 去掉首尾 $
    # 去除 LaTeX 命令和花括号
    cleaned = re.sub(r'\\[a-zA-Z]+', ' ', content)
    cleaned = re.sub(r'[{}^_]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # 如果剩余内容有意义（含有字母数字或中文），保留
    if re.search(r'[a-zA-Z0-9\u4e00-\u9fff]', cleaned):
        return cleaned
    return ' '


def _replace_url(match: re.Match) -> str:
    """从 URL 中提取域名关键词。

    例如：https://docs.example.com/api/v2/users → docs example
    """
    url = match.group(0)
    try:
        # 提取域名部分
        domain_match = re.search(r'https?://([^/]+)', url)
        if domain_match:
            domain = domain_match.group(1)
            # 去除 www. 和顶级域名
            parts = domain.replace('www.', '').split('.')
            meaningful = [p for p in parts if len(p) > 2 and p not in ('com', 'org', 'net', 'cn', 'io')]
            if meaningful:
                return ' ' + ' '.join(meaningful) + ' '
    except Exception:
        pass
    return ' '


def _replace_filepath(match: re.Match) -> str:
    """从文件路径中提取文件名（如有意义）。

    例如：/usr/local/share/doc/manual.pdf → manual
          /opt/data/cache/a1b2c3d4e5f6a7b8.bin → ''（hash 文件名，无意义）
    """
    path = match.group(0)
    # 取最后一个路径组件
    parts = re.split(r'[/\\]', path)
    if parts:
        filename = parts[-1]
        # 去除扩展名
        name = re.sub(r'\.\w{1,5}$', '', filename)
        # 如果文件名有意义（非 hash，含有非hex字符或长度合理的有意义词）
        if name and not re.match(r'^[a-f0-9]{8,}$', name, re.IGNORECASE):
            return f' {name} '
    return ' '


def _replace_mathrm_chain(match: re.Match) -> str:
    """从连续 \\mathrm{X} 链中提取花括号内的有效文本。

    例如：\\mathrm{T}\\mathrm{6}\\mathrm{.}\\mathrm{T}\\mathrm{1} → T6.T1
          \\mathrm{db}\\mathrm{IIC} → dbIIC
    """
    text = match.group(0)
    # 提取所有 \mathrm{...} 或 \\mathrm{...} 中花括号的内容
    contents = re.findall(r'\\{1,2}mathrm\{([^}]*)\}', text)
    # 过滤掉 LaTeX 命令（\leq 等）和空白占位（~）
    meaningful = []
    for c in contents:
        c = c.strip()
        if not c or c.startswith('\\') or c == '~' or c.startswith('~'):
            continue
        meaningful.append(c)
    result = ''.join(meaningful)
    # 如果提取结果有意义，返回它
    if result and re.search(r'[a-zA-Z0-9\u4e00-\u9fff]', result):
        return f' {result} '
    return ' '


def _replace_text_chain(match: re.Match) -> str:
    """从连续 \\text{X} 链中提取有效文本。"""
    text = match.group(0)
    contents = re.findall(r'\\{1,2}text\{([^}]*)\}', text)
    meaningful = [c.strip() for c in contents if c.strip() and not c.startswith('\\')]
    result = ''.join(meaningful)
    if result and re.search(r'[a-zA-Z0-9\u4e00-\u9fff]', result):
        return f' {result} '
    return ' '
