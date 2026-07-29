-- 沙盒执行工具初始化 — 远程命令执行、文件操作、代码运行
-- 执行方式: psql -f sql/migrate_add_sandbox_tools.sql
-- 或通过 scripts/run_migrate_sandbox_tools.py 执行

SET search_path TO paas_ai;

INSERT INTO ai_tool_definition
(id, api_key, tenant_id, name, description, input_schema, prompt,
 category, tags, icon, read_only_flg, destructive_flg,
 enabled_flg, system_flg, sort_num, ext_info,
 delete_flg, created_at, created_by, updated_at, updated_by)
VALUES
-- terminal: 远程 Shell 命令执行
(3000000000000101, 'terminal', 0,
 '远程终端',
 '在远程沙盒环境中执行 Shell 命令，支持所有标准 Linux 命令，工作目录和环境变量跨命令保持',
 '{"type":"object","properties":{"command":{"type":"string","description":"要执行的 Shell 命令"},"timeout":{"type":"integer","description":"超时时间（秒），默认 180","default":180}},"required":["command"]}',
 'terminal — 在远程沙盒中执行 Shell 命令。支持所有标准 Linux 命令。工作目录和环境变量跨命令保持。用法: terminal(command=''npm install express'')',
 'sandbox', '["shell","command","execute"]', '💻',
 0, 0, 1, 1, 100, '{}',
 0, 1748131200000, 0, 1748131200000, 0),

-- execute_code: 远程代码执行
(3000000000000102, 'execute_code', 0,
 '代码执行',
 '在远程沙盒中执行代码片段，支持 Python、JavaScript、Bash、Ruby、Go',
 '{"type":"object","properties":{"language":{"type":"string","description":"编程语言","enum":["python","python3","javascript","js","node","bash","sh","ruby","go"]},"code":{"type":"string","description":"要执行的代码"},"timeout":{"type":"integer","description":"超时时间（秒），默认 60","default":60}},"required":["language","code"]}',
 'execute_code — 在远程沙盒中执行代码片段。支持语言: python, javascript, bash, ruby, go。代码在隔离环境中执行，可以安装和使用第三方库。',
 'sandbox', '["code","python","javascript","run"]', '⚡',
 0, 0, 1, 1, 110, '{}',
 0, 1748131200000, 0, 1748131200000, 0),

-- read_file: 远程文件读取
(3000000000000103, 'read_file', 0,
 '读取文件',
 '读取远程沙盒中的文件内容，支持按行范围读取大文件',
 '{"type":"object","properties":{"path":{"type":"string","description":"文件路径（绝对路径或相对于工作目录）"},"offset":{"type":"integer","description":"起始行号（从 0 开始），默认 0","default":0},"limit":{"type":"integer","description":"读取行数，默认 2000","default":2000}},"required":["path"]}',
 'read_file — 读取远程沙盒中的文件内容。支持按行范围读取大文件。',
 'sandbox', '["file","read"]', '📄',
 1, 0, 1, 1, 120, '{}',
 0, 1748131200000, 0, 1748131200000, 0),

-- write_file: 远程文件写入
(3000000000000104, 'write_file', 0,
 '写入文件',
 '在远程沙盒中创建或覆盖文件，自动创建父目录',
 '{"type":"object","properties":{"path":{"type":"string","description":"文件路径"},"content":{"type":"string","description":"文件内容"}},"required":["path","content"]}',
 'write_file — 在远程沙盒中创建或覆盖文件。自动创建父目录。',
 'sandbox', '["file","write","create"]', '📝',
 0, 0, 1, 1, 130, '{}',
 0, 1748131200000, 0, 1748131200000, 0),

-- search_files: 远程文件搜索
(3000000000000105, 'search_files', 0,
 '搜索文件',
 '在远程沙盒中递归搜索文件内容，支持正则表达式和文件名过滤',
 '{"type":"object","properties":{"pattern":{"type":"string","description":"搜索模式（支持正则）"},"path":{"type":"string","description":"搜索目录，默认当前目录","default":"."},"include":{"type":"string","description":"文件名过滤（如 *.py）","default":""}},"required":["pattern"]}',
 'search_files — 在远程沙盒中搜索文件内容。使用 grep 进行递归搜索，支持正则表达式。',
 'sandbox', '["file","search","grep"]', '🔍',
 1, 0, 1, 1, 140, '{}',
 0, 1748131200000, 0, 1748131200000, 0)

ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;
