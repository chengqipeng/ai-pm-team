"""
Skills 体系 — 借鉴 bundledSkills.ts / loadSkillsDir.ts / SkillTool.ts
多源加载 + 动态发现 + 隔离执行

Skill 的本质: 一段精心设计的 prompt，注入到子 Agent 的上下文中，
由子 Agent 的 agentic loop + tools 完成实际执行。
Skill 本身不执行任何操作 — 它只生成指令。

借鉴源码:
  - src/skills/bundled/verify.ts: 验证技能的完整 prompt
  - src/skills/bundled/debug.ts: 调试技能
  - src/skills/bundled/stuck.ts: 自救技能
  - src/skills/bundled/remember.ts: 记忆持久化
  - src/skills/bundled/batch.ts: 批量处理
  - src/skills/bundled/loop.ts: 循环执行
  - src/skills/bundled/simplify.ts: 代码简化
  - src/skills/bundled/skillify.ts: 操作转技能
  - src/skills/loadSkillsDir.ts: 文件技能加载
  - src/skills/bundledSkills.ts: 注册机制
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from .types import ToolResult, Message
from .tools import Tool, ToolUseContext


# ─── Skill 定义 ───

@dataclass
class SkillDefinition:
    """技能定义 (借鉴 bundledSkills.ts:BundledSkillDefinition)"""
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    when_to_use: str | None = None
    argument_hint: str | None = None
    allowed_tools: list[str] | None = None
    model: str | None = None
    context: str = "fork"  # "inline" | "fork"
    agent: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    get_prompt: Callable[..., Awaitable[str]] | None = None
    source: str = "bundled"


# ─── Skill 注册表 ───

class SkillRegistry:
    """技能注册与加载 (借鉴 bundledSkills.ts + loadSkillsDir.ts)"""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, skill: SkillDefinition) -> None:
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._alias_map[alias] = skill.name

    def find(self, name: str) -> SkillDefinition | None:
        if name in self._skills:
            return self._skills[name]
        canonical = self._alias_map.get(name)
        return self._skills.get(canonical) if canonical else None

    def load_from_directory(self, directory: str, source: str = "project") -> int:
        loaded = 0
        skills_dir = Path(directory)
        if not skills_dir.is_dir():
            return 0
        for md_file in skills_dir.rglob("*.md"):
            skill = self._parse_skill_file(md_file, source)
            if skill:
                self.register(skill)
                loaded += 1
        return loaded

    def load_all_sources(self, project_root: str = ".") -> int:
        total = 0
        user_dir = Path.home() / ".claude" / "skills"
        total += self.load_from_directory(str(user_dir), "user")
        project_dir = Path(project_root) / ".claude" / "skills"
        total += self.load_from_directory(str(project_dir), "project")
        return total

    @property
    def all_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def _parse_skill_file(self, path: Path, source: str) -> SkillDefinition | None:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None
        frontmatter, body = _parse_frontmatter(content)
        name = frontmatter.get("name", path.stem)
        description = frontmatter.get("description", "")
        aliases = frontmatter.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",")]
        allowed_tools = frontmatter.get("allowed-tools")
        if isinstance(allowed_tools, str):
            allowed_tools = [t.strip() for t in allowed_tools.split(",")]

        # 捕获 path 到闭包中，避免延迟绑定问题
        _body = body
        _parent = str(path.parent)

        async def get_prompt(args: str = "", **kwargs) -> str:
            prompt = _body
            prompt = prompt.replace("${1}", args)
            prompt = prompt.replace("${CLAUDE_SKILL_DIR}", _parent)
            return prompt

        return SkillDefinition(
            name=name, description=description, aliases=aliases,
            when_to_use=frontmatter.get("when-to-use"),
            argument_hint=frontmatter.get("argument-hint"),
            allowed_tools=allowed_tools,
            model=frontmatter.get("model"),
            context=frontmatter.get("context", "fork"),
            source=source, get_prompt=get_prompt,
        )


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()
    fm: dict[str, Any] = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].split(",")
                fm[key] = [i.strip().strip("'\"") for i in items if i.strip()]
            else:
                fm[key] = value.strip("'\"")
    return fm, body


# ═══════════════════════════════════════════════════════════════
# 内置技能 — 完整 prompt 实现
# 借鉴 src/skills/bundled/ 目录下的每个技能文件
# ═══════════════════════════════════════════════════════════════

def register_builtin_skills(registry: SkillRegistry) -> None:
    """注册全部 8 个内置技能 (借鉴 src/skills/bundled/index.ts)"""

    # ─── 1. verify (借鉴 bundled/verify.ts + verifyContent.ts) ───

    async def verify_prompt(args: str = "", **kw) -> str:
        focus = f"\n\nFocus area: {args}" if args else ""
        return f"""You are a verification specialist. Your job is to verify that recent code changes are correct.

## Verification Steps

1. **Identify what changed**: Use `bash` to run `git diff` and `git diff --cached` to see all recent changes. If no git changes, check the conversation history for what was modified.

2. **Run existing tests**: Look for test configuration files (package.json scripts, pytest.ini, Makefile, etc.) and run the appropriate test command:
   - Python: `python -m pytest` or `pytest`
   - JavaScript/TypeScript: `npm test` or `npx jest` or `npx vitest --run`
   - Go: `go test ./...`
   - Rust: `cargo test`
   - If no test framework found, note this.

3. **Check for syntax errors**: For each modified file:
   - Python: `python -m py_compile <file>`
   - JavaScript/TypeScript: `npx tsc --noEmit` or check with the project's lint command
   - Run the project's linter if configured (eslint, ruff, flake8, etc.)

4. **Validate logic**: Read each modified file and verify:
   - The changes match the intended behavior
   - Edge cases are handled
   - No obvious bugs (null checks, off-by-one, resource leaks)
   - Error handling is appropriate

5. **Check for regressions**: Verify that the changes don't break existing functionality by:
   - Running the full test suite (not just tests for changed files)
   - Checking imports and dependencies

## Output Format

Report your findings as:
- ✅ PASS: [what passed]
- ❌ FAIL: [what failed and why]
- ⚠️ WARNING: [potential issues]

End with a clear VERDICT: PASS or FAIL with explanation.{focus}"""

    registry.register(SkillDefinition(
        name="verify", description="Verify code changes by running tests, linting, and logic checks",
        aliases=["v", "check"],
        when_to_use="After making code changes, verify correctness automatically",
        argument_hint="Optional focus area, e.g. 'auth module' or 'the new API endpoint'",
        allowed_tools=["bash", "file_read", "grep", "glob"],
        context="fork", get_prompt=verify_prompt,
    ))

    # ─── 2. debug (借鉴 bundled/debug.ts) ───

    async def debug_prompt(args: str = "", **kw) -> str:
        return f"""You are a systematic debugger. Debug the following issue step by step.

## Issue
{args or "[No specific issue provided — investigate recent errors or failures]"}

## Debugging Protocol

### Phase 1: Reproduce
- Identify the exact command or action that triggers the issue
- Run it and capture the full error output (stdout + stderr)
- Note the exact error message, stack trace, and exit code

### Phase 2: Locate
- Parse the stack trace to identify the failing file and line number
- Read the relevant source code around the failure point
- Search for related code using grep (error messages, function names, variable names)
- Check recent git changes that might have introduced the bug: `git log --oneline -10` and `git diff HEAD~3`

### Phase 3: Understand
- Identify the root cause (not just the symptom)
- Determine if this is a:
  - Logic error (wrong condition, missing case)
  - Type error (wrong type, null/undefined)
  - State error (race condition, stale data)
  - Configuration error (wrong env var, missing dependency)
  - Integration error (API contract mismatch)

### Phase 4: Fix
- Implement the minimal fix that addresses the root cause
- Do NOT fix symptoms — fix the underlying problem
- If the fix is non-trivial, explain your reasoning

### Phase 5: Verify
- Run the failing command again to confirm the fix works
- Run the full test suite to check for regressions
- If tests fail, iterate on the fix

## Rules
- Always show your work: print commands and their output
- If you can't reproduce the issue, say so and explain what you tried
- If the fix requires changes to multiple files, list all changes
- If you're unsure about the root cause, present your top 2-3 hypotheses"""

    registry.register(SkillDefinition(
        name="debug", description="Systematically debug an issue: reproduce → locate → understand → fix → verify",
        aliases=["d", "fix"],
        when_to_use="When there's a bug, error, or test failure to investigate",
        argument_hint="Description of the issue, error message, or failing test",
        context="fork", get_prompt=debug_prompt,
    ))

    # ─── 3. stuck (借鉴 bundled/stuck.ts) ───

    async def stuck_prompt(args: str = "", **kw) -> str:
        return """You appear to be stuck in a loop or making no progress. Step back and apply this recovery protocol:

## Self-Assessment
1. What was the original goal?
2. What approaches have you tried so far?
3. Why did each approach fail?
4. Are you repeating the same action expecting different results?

## Recovery Strategies (try in order)

### Strategy 1: Re-read the error
- Read the FULL error message carefully, not just the first line
- Look for "caused by" or "root cause" sections
- Check if the error message suggests a fix

### Strategy 2: Broaden your search
- If you've been looking in one file, search the whole codebase
- Use `grep -r` with different search terms
- Check configuration files, environment variables, dependencies

### Strategy 3: Simplify
- Can you reproduce the issue with a minimal example?
- Remove complexity until you find the breaking change
- Try the simplest possible fix first

### Strategy 4: Check assumptions
- Verify file paths exist: `ls -la <path>`
- Verify commands work: `which <command>`
- Verify environment: `env | grep RELEVANT_VAR`
- Verify dependencies: `pip list` / `npm list` / `cat package.json`

### Strategy 5: Ask the user
- If you've exhausted all strategies, use the ask_user tool
- Be specific about what you need: "I've tried X, Y, Z. Can you clarify...?"
- Don't ask vague questions — show what you've tried

## Anti-Patterns to Avoid
- ❌ Running the same command repeatedly
- ❌ Editing the same line back and forth
- ❌ Reading the same file without acting on what you find
- ❌ Ignoring error messages"""

    registry.register(SkillDefinition(
        name="stuck", description="Self-rescue protocol when stuck in a loop or making no progress",
        aliases=["unstuck", "help"],
        when_to_use="When the agent detects it's stuck (3+ same tool calls or 3+ consecutive errors)",
        context="inline",  # inline: 直接注入当前对话，不启动子 Agent
        get_prompt=stuck_prompt,
    ))

    # ─── 4. remember (借鉴 bundled/remember.ts) ───

    async def remember_prompt(args: str = "", **kw) -> str:
        return f"""Save the following information to the project's memory file for future reference.

## What to Save
{args or "[No specific content provided]"}

## Instructions
1. Read the existing CLAUDE.md file in the project root (if it exists)
2. Append the new information under an appropriate section heading
3. If CLAUDE.md doesn't exist, create it with a clear structure
4. Use this format:

```markdown
## [Category]

- [Information to remember]
```

## Rules
- Do NOT duplicate information already in the file
- Keep entries concise and actionable
- Use categories like: Architecture, Conventions, Commands, Known Issues, Dependencies
- If the information contradicts existing content, update the existing entry
- Write the file using the file_write or file_edit tool

## File Location
Write to: CLAUDE.md (project root)
If the user specified a different location, use that instead."""

    registry.register(SkillDefinition(
        name="remember", description="Persist information to CLAUDE.md memory file for future sessions",
        aliases=["mem", "save"],
        when_to_use="When the user says 'remember this' or wants to save project knowledge",
        argument_hint="Information to save, e.g. 'always run tests with --verbose flag'",
        allowed_tools=["file_read", "file_write", "file_edit"],
        context="fork", get_prompt=remember_prompt,
    ))

    # ─── 5. batch (借鉴 bundled/batch.ts) ───

    async def batch_prompt(args: str = "", **kw) -> str:
        return f"""Process multiple files with the same operation.

## Task
{args or "[No batch task specified]"}

## Protocol
1. **Discover files**: Use `glob` or `grep` to find all files matching the criteria
2. **Preview**: Show the list of files that will be affected and the planned change
3. **Execute**: Apply the operation to each file one by one
4. **Report**: After processing all files, report:
   - Total files found
   - Files successfully modified
   - Files skipped (and why)
   - Files that errored (and why)

## Rules
- Process files one at a time (not all at once) so errors are isolated
- If a file fails, continue with the remaining files
- Use file_edit for modifications (not file_write) to preserve unrelated content
- Show a progress count: "Processing file 3/15: src/foo.py"
- If more than 20 files match, ask the user to confirm before proceeding"""

    registry.register(SkillDefinition(
        name="batch", description="Apply the same operation to multiple files matching a pattern",
        aliases=["b", "bulk"],
        when_to_use="When the user wants to make the same change across many files",
        argument_hint="e.g. 'add type hints to all Python files in src/'",
        context="fork", get_prompt=batch_prompt,
    ))

    # ─── 6. loop (借鉴 bundled/loop.ts) ───

    async def loop_prompt(args: str = "", **kw) -> str:
        return f"""Execute a task repeatedly until a success condition is met.

## Task
{args or "[No loop task specified]"}

## Protocol
1. **Understand the goal**: What does "success" look like? Define a concrete, testable condition.
2. **Execute one iteration**: Perform the task once.
3. **Check the condition**: Run a verification command to test if the goal is met.
4. **If not met**: Analyze what went wrong, adjust your approach, and try again.
5. **If met**: Report success and stop.

## Iteration Tracking
- Keep count of iterations: "Iteration 1/10..."
- Maximum 10 iterations (to prevent infinite loops)
- After each iteration, briefly note what you tried and what happened

## Exit Conditions (stop immediately if any are true)
- ✅ Success condition is met
- ❌ Maximum iterations (10) reached
- ❌ Same error occurs 3 times in a row (you're stuck — try a different approach)
- ❌ The task is fundamentally impossible (explain why)

## Rules
- Each iteration should try something DIFFERENT if the previous one failed
- Don't just retry the same thing — analyze the failure and adapt
- If you reach iteration 5 without progress, reconsider the entire approach"""

    registry.register(SkillDefinition(
        name="loop", description="Repeat a task until a success condition is met (max 10 iterations)",
        aliases=["l", "repeat", "retry"],
        when_to_use="When a task needs iterative refinement (e.g. 'keep fixing until tests pass')",
        argument_hint="e.g. 'fix the build errors until `npm run build` succeeds'",
        context="fork", get_prompt=loop_prompt,
    ))

    # ─── 7. simplify (借鉴 bundled/simplify.ts) ───

    async def simplify_prompt(args: str = "", **kw) -> str:
        return f"""Simplify the specified code while preserving its behavior.

## Target
{args or "[No specific code specified — simplify the most recently modified files]"}

## Simplification Checklist
1. **Read the code**: Understand what it does before changing anything
2. **Identify complexity**: Look for:
   - Deeply nested conditionals (flatten with early returns)
   - Duplicated logic (extract into functions)
   - Overly verbose patterns (use language idioms)
   - Dead code (unused imports, unreachable branches)
   - Unnecessary abstractions (remove indirection that adds no value)
3. **Apply simplifications**: One at a time, verify after each change
4. **Verify behavior**: Run tests after simplification to ensure nothing broke

## Rules
- NEVER change behavior — only simplify structure
- Prefer readability over cleverness
- Keep changes small and reviewable
- If tests exist, run them after each change
- If no tests exist, be extra careful and explain each change

## Anti-Patterns to Fix
- `if x == True:` → `if x:`
- `if x: return True else: return False` → `return x`
- Nested try/except with identical handlers → single try/except
- `for i in range(len(lst)):` → `for item in lst:` or `for i, item in enumerate(lst):`
- Manual string concatenation in loops → `''.join()` or f-strings"""

    registry.register(SkillDefinition(
        name="simplify", description="Simplify code while preserving behavior: flatten, deduplicate, idiomize",
        aliases=["s", "clean", "refactor"],
        when_to_use="When code is overly complex, nested, or verbose",
        argument_hint="File path or description, e.g. 'src/auth/handler.py' or 'the login function'",
        context="fork", get_prompt=simplify_prompt,
    ))

    # ─── 8. skillify (借鉴 bundled/skillify.ts) ───

    async def skillify_prompt(args: str = "", **kw) -> str:
        return f"""Convert the described operation into a reusable skill file.

## Operation to Convert
{args or "[Describe the operation you want to turn into a skill]"}

## Output Format
Create a skill file at `.claude/skills/<skill-name>.md` with this structure:

```markdown
---
name: <skill-name>
description: <one-line description>
when-to-use: <when should this skill be triggered>
allowed-tools: [<list of tools this skill needs>]
context: fork
---

<Detailed prompt that instructs the agent how to perform this operation>

The prompt should:
1. Explain the goal clearly
2. List step-by-step instructions
3. Specify what tools to use and how
4. Define success criteria
5. Handle edge cases
```

## Rules
- The skill name should be lowercase, hyphenated (e.g. `run-migrations`)
- The prompt should be self-contained — the agent running it has no prior context
- Use ${{1}} as a placeholder for user arguments
- Use ${{CLAUDE_SKILL_DIR}} to reference files bundled with the skill
- Test the skill by reading it back and verifying the prompt makes sense
- Keep the prompt under 2000 characters for efficiency"""

    registry.register(SkillDefinition(
        name="skillify", description="Convert an operation into a reusable .claude/skills/ skill file",
        aliases=["sk", "create-skill"],
        when_to_use="When the user wants to save a repeatable workflow as a skill",
        argument_hint="Description of the operation, e.g. 'deploy to staging with database migration'",
        allowed_tools=["file_read", "file_write", "file_edit", "bash", "glob"],
        context="fork", get_prompt=skillify_prompt,
    ))
