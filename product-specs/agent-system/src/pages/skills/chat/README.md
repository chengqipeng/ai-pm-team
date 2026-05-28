# 对话式创建 Skill — 前端组件

## 概述

本目录包含"通过对话创建 Skill"功能的前端组件，核心交互流程：

1. 用户在 Chat 中说"帮我创建一个技能"
2. Agent 生成技能定义后调用 `ask_user(interrupt_type="skill_confirm")`
3. LangGraph `interrupt()` 暂停执行，前端收到中断事件
4. 前端渲染 `SkillConfirmCard`，展示技能预览
5. 用户可以：确认 / 修改后确认 / 取消
6. 前端调用 `resume` 接口恢复 Agent 执行
7. Agent 收到确认后调用 `manage_skill(create)` 写入数据库

**关键约束：只有用户点击"确认创建"后，Agent 才会执行实际的保存操作。**

## 组件清单

| 组件 | 职责 |
|------|------|
| `SkillConfirmCard` | 核心确认卡片（预览/编辑/确认/取消） |
| `SkillPreview` | 只读预览技能定义 |
| `SkillInlineEditor` | 内联编辑技能定义 |
| `SkillCreatedCard` | 创建成功后的提示卡片 |
| `SkillSuggestionBubble` | "要不要保存为技能？"建议气泡 |
| `SkillPromptStarters` | 快捷提示词入口（WelcomeScreen / InputBox） |
| `InterruptSkillRenderer` | 中断渲染路由（判断 + 分发） |

## 集成方式

### 0. 在 WelcomeScreen / InputBox 中添加快捷提示词入口

```tsx
// 方式 A: WelcomeScreen 中作为快捷卡片
import { SkillPromptStarters } from '@/pages/skills/chat';

function WelcomeScreen({ onSend }) {
  return (
    <div className="welcome-grid">
      {/* 其他快捷卡片 */}
      <SkillPromptStarters onSelect={onSend} variant="card" />
    </div>
  );
}

// 方式 B: InputBox 上方作为胶囊按钮
import { SkillPromptStarters } from '@/pages/skills/chat';

function InputBox({ onSend }) {
  return (
    <div className="input-area">
      <SkillPromptStarters onSelect={onSend} variant="chip" />
      <textarea placeholder="输入消息..." />
    </div>
  );
}

// 方式 C: 直接使用预置提示词数据
import { SKILL_PROMPT_STARTERS } from '@/pages/skills/chat';

// SKILL_PROMPT_STARTERS 是一个数组，每项包含:
// { id, icon, title, description, prompt }
// 可以自由组合到任何 UI 中
```

### 1. 在 Chat 的 InterruptRenderer 中注册

```tsx
// src/components/chat/InterruptRenderer.tsx
import { isSkillInterrupt, InterruptSkillRenderer } from '@/pages/skills/chat';

function InterruptRenderer({ data, onResume, disabled }) {
  // Skill 确认中断
  if (isSkillInterrupt(data)) {
    return <InterruptSkillRenderer data={data} onResume={onResume} disabled={disabled} />;
  }

  // 其他中断类型...
  switch (data.type) {
    case 'confirm':
      return <ConfirmCard data={data} onResume={onResume} />;
    case 'select':
      return <SelectCard data={data} onResume={onResume} />;
    default:
      return <GenericInterrupt data={data} onResume={onResume} />;
  }
}
```

### 2. 处理 CUSTOM 事件中的 skill_created

```tsx
// 在 Chat SSE 事件处理中
function handleCustomEvent(event) {
  if (event.name === 'skill_created') {
    // 渲染 SkillCreatedCard
    appendMessage({
      type: 'component',
      component: 'SkillCreatedCard',
      props: event.value,
    });
  }
  if (event.name === 'skill_suggestion') {
    // 渲染 SkillSuggestionBubble
    appendMessage({
      type: 'component',
      component: 'SkillSuggestionBubble',
      props: event.value,
    });
  }
}
```

### 3. Resume 接口调用

```tsx
// onResume 回调的实现
async function handleResume(threadId: string, runId: string, value: any) {
  await fetch('/api/chat/agui/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      thread_id: threadId,
      resume_value: value,
    }),
  });
}
```

## 数据流

```
ask_user(interrupt_type="skill_confirm", options=[{description: JSON}])
    │
    ▼ LangGraph interrupt()
    │
    ▼ SSE 事件: __interrupt__ → {interrupt_value: {...}}
    │
    ▼ 前端: InterruptRenderer → isSkillInterrupt() → SkillConfirmCard
    │
    ├── [确认] → onResume({action: "confirm", value: definition})
    ├── [修改] → SkillInlineEditor → 修改 → 回到预览 → [确认]
    └── [取消] → onResume({cancelled: true})
    │
    ▼ POST /api/chat/agui/resume
    │
    ▼ Agent 恢复: interrupt() 返回 resume_value
    │
    ├── action=confirm → manage_skill(create, skill_definition=value)
    └── cancelled=true → 回复"已取消"
```

## 技术依赖

- React 19
- Ant Design 6
- LangGraph interrupt/resume 机制
- AG-UI SSE 事件流
