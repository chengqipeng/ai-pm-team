# Mem0 vs OpenViking vs FTSMemoryEngine — 源码级深度对比（toB CRM 视角）

> 基于 Mem0 `mem0/memory/main.py`（V3 Phased Batch Pipeline，~3700行）、OpenViking 官方文档 + RFC + 项目方案文档、FTSMemoryEngine `src/memory/fts_engine.py` + `storage.py`（~600行）的源码级分析。
> 所有结论均可追溯到具体代码逻辑。

---

## 一、记忆写入流水线：源码逻辑逐步拆解

### 1.1 Mem0 的 V3 Phased Batch Pipeline

Mem0 最新版已从早期"2次LLM调用（提取+决策 ADD/UPDATE/DELETE/NOOP）"简化为单次 Additive Extraction。核心在 `_add_to_vector_store()` 方法，8个Phase：

```
Phase 0: Context gathering
  → db.get_last_messages(session_scope, limit=10)   # SQLite取最近10条历史消息
  → parse_messages(messages)                         # 拼接为纯文本

Phase 1: Existing memory retrieval
  → embedding_model.embed(parsed_messages, "search") # 向量化当前对话
  → vector_store.search(top_k=10, filters)           # 检索已有记忆
  → 将已有记忆的UUID映射为整数ID（防LLM幻觉编造memory_id）

Phase 2: LLM extraction（单次调用，核心成本点）
  → ADDITIVE_EXTRACTION_PROMPT 系统提示
  → 输入：existing_memories + new_messages + last_k_messages + custom_instructions
  → 输出：JSON {"memory": [{"text": "...", "attributed_to": "..."}]}
  → V3只做ADD，不再做UPDATE/DELETE（通过linked_memory_ids关联去重）

Phase 3: Batch embed
  → embedding_model.embed_batch(mem_texts, "add")    # 批量向量化所有提取结果

Phase 4-5: Hash dedup
  → MD5(text) 与已有记忆hash + 当前批次内hash去重
  → lemmatize_for_bm25(text)                         # BM25词形还原预处理

Phase 6: Batch persist
  → vector_store.insert(vectors, ids, payloads)      # 批量写入向量库
  → db.batch_add_history(history_records)             # 批量写入SQLite审计日志

Phase 7: Batch entity linking（实体关联，新增能力）
  → extract_entities_batch(all_texts)                 # 批量NER实体提取
  → 全局去重 → 批量embed → 批量搜索已有实体(score>=0.95则合并)
  → 新实体批量insert，已有实体更新linked_memory_ids

Phase 8: Save messages + return
```

源码中的关键设计决策：

- `_search_vector_store()` 实现了**三路混合检索**：语义搜索（over-fetch 4x）+ BM25关键词搜索 + 实体boost，通过 `score_and_rank()` 加权融合
- 实体boost有**扩散衰减**：`memory_count_weight = 1.0 / (1.0 + 0.001 * ((num_linked - 1) ** 2))`，链接记忆越多的实体boost越低，防止热门实体主导排序
- 去重从LLM判断改为**MD5 hash精确去重**，消除了LLM非确定性导致的重复/遗漏

**CRM 场景关键问题：**

- **每次 add() 都要调用 LLM**（Phase 2），即使是简单的"查一下客户列表"也要走 LLM 提取。对于 CRM 高频短对话（销售每天几十次查询），LLM 成本线性增长
- **无防抖机制**：连续快速对话会产生大量 LLM 调用，无合并窗口
- **实体提取是通用 NER**（`extract_entities` 基于 spaCy/regex），不理解 CRM 业务对象（Account/Opportunity/Contact/Lead）的语义关系

### 1.2 OpenViking 的会话压缩触发 + 8类分类提取

OpenViking 的写入不是每条消息触发，而是**双阈值Compact上报**：

```
会话消息流 → 阈值检测：
  ├── 50%上下文窗口 → 后台异步上报（不阻塞主流程）
  ├── 70%上下文窗口 → 强制清理已上报消息
  └── 会话结束(/new或超时) → 全量提取剩余消息

提取流水线（6步）：
  1. 消息预处理：过滤噪声（问候语、确认语）、合并连续同角色消息
  2. 意图分析：识别对话主题、关键实体、用户意图
  3. 8类记忆提取：LLM按profile/preferences/entities/events/cases/patterns/tools/skills分类
  4. 去重与冲突检测：语义相似度阈值（0.8~0.9）+ LLM判断
  5. 质量评分：置信度 × 重要性
  6. 写入存储：生成L0/L1/L2三层内容 → 写入MemoryFS + 向量索引

L0/L1/L2生成（SemanticProcessor自底向上）：
  叶子节点记忆 → L0摘要(~100 tokens) → L1概览(~2k tokens) → L2原始完整内容
  父目录 → 聚合子节点L0 → 生成父级L1 → 生成父级L0
```

关键设计决策：

- **不是每条消息都触发LLM**，而是攒到阈值才批量处理，天然适合长对话场景
- 8类分类体系中 `entities`（人、项目、业务对象）和 `events`（决策、里程碑）对CRM有直接映射
- L0/L1/L2三层模型是OpenViking最核心的创新——检索时先看100 token的摘要，确认相关再加载2k的概览，最后才按需加载完整内容

### 1.3 FTSMemoryEngine 的规则优先 + LLM增强

FTSMemoryEngine 的 `extract_and_update()` 走的是完全不同的路线——**规则驱动为主，LLM为辅**：

```python
# 源码逻辑（fts_engine.py extract_and_update方法）：

# 维度1: task_history — 直接拼接，同thread去重
task_summary = f"问: {last_human[:200]}\n答: {last_ai[:300]}"
if tool_names_used:
    task_summary += f"\n使用工具: {', '.join(tool_names_used[:5])}"
# 删除同thread旧记录 → 写入新记录（SQL DELETE + INSERT）

# 维度2: user_profile — 偏好标记词检测（纯规则）
preference_markers = ["我喜欢", "我习惯", "我偏好", "请用", "我需要", "我是",
                      "以后都", "默认用", "不要用", "别用"]
for marker in preference_markers:
    if marker in last_human:  # 命中任一标记词就提取
        storage.add(user_id, content=last_human[:500], dimension="user_profile")
        break

# 维度3: customer_context — 实体正则提取
_ENTITY_PATTERNS = [
    re.compile(r'[\u4e00-\u9fff]{2,6}(?:科技|公司|集团|有限|股份|银行|保险|证券)'),  # 公司名
    re.compile(r'[\u4e00-\u9fff]{2,3}(?=的|说|要|给|跟|和|与)'),                    # 人名
    re.compile(r'(?:account|opportunity|contact|lead|activity)\b', re.IGNORECASE),   # CRM实体
]

# 维度4: domain_knowledge — LLM提取（仅此维度用LLM）
if self._llm is not None:
    updater = MemoryUpdater(llm=self._llm)
    updated = await updater.extract_and_update(messages[-6:], existing_knowledge)
```

关键设计决策：

- **4个维度中只有1个用LLM**（domain_knowledge），其余3个纯规则，LLM成本降低75%
- `_ENTITY_PATTERNS` 内置了CRM业务实体关键词（account/opportunity/contact/lead），这是Mem0和OpenViking都没有的
- 通过 `DebounceQueue`（`queue.py`）实现防抖：`debounce_seconds=5.0`，5秒内的多次提交合并为一次处理
- 同thread的task_history通过SQL `DELETE WHERE thread_id = ?` 精确去重，不依赖语义相似度

---

## 二、记忆检索流水线：源码逻辑对比

### 2.1 Mem0 的三路混合检索

`_search_vector_store()` 方法实现了9步检索流程：

```python
# Step 1: 查询预处理
query_lemmatized = lemmatize_for_bm25(query)      # 词形还原
query_entities = extract_entities(query)            # NER实体提取

# Step 2: 向量化
embeddings = self.embedding_model.embed(query, "search")

# Step 3: 语义搜索（4倍over-fetch）
internal_limit = max(limit * 4, 60)
semantic_results = vector_store.search(top_k=internal_limit, filters=filters)

# Step 4: BM25关键词搜索
keyword_results = vector_store.keyword_search(query=query_lemmatized, top_k=internal_limit)

# Step 5: BM25分数归一化（sigmoid函数）
bm25_scores[mem_id] = normalize_bm25(raw_score, midpoint, steepness)

# Step 6: 实体boost计算
for entity in query_entities:
    matches = entity_store.search(entity_embedding, top_k=500, filters)
    for match in matches:
        if similarity >= 0.5:
            boost = similarity * ENTITY_BOOST_WEIGHT * memory_count_weight
            memory_boosts[memory_id] = max(existing_boost, boost)

# Step 7-8: 候选集构建 + score_and_rank()加权融合
scored_results = score_and_rank(semantic_results, bm25_scores, entity_boosts, threshold, top_k)
```

**CRM场景分析：**

- 三路融合（语义+BM25+实体）对CRM查询很有价值——"华为的商机"既需要语义理解"商机"，也需要精确匹配"华为"，还需要实体关联
- 但 `extract_entities()` 是通用NER，不理解CRM领域的实体层级（Account → Contact → Opportunity → Activity）
- 4倍over-fetch + 实体boost的top_k=500 意味着每次检索要扫描大量候选，对于记忆量大的租户可能有性能问题

### 2.2 OpenViking 的目录递归检索

这是OpenViking最核心的检索创新，与传统"一次性向量搜索碎片"完全不同：

```
Step 1: 意图分析
  → LLM生成0~5个类型化子查询
  → 例："上周关于数据库优化的讨论" →
      时间查询: "上周的对话"
      主题查询: "数据库优化"
      事件查询: "讨论和决策"

Step 2: 初始定位（向量检索L0摘要）
  → 对每个子查询检索L0摘要 → 命中高分目录
  → 例: 命中 user/memories/events/ 和 agent/memories/cases/

Step 3: 目录内精细探索
  → 在高分目录内执行二次检索（向量+关键词）
  → 加载L1概览进行重排序

Step 4: 递归下钻（优先队列管理）
  → 高分目录有子目录 → 递归Step 3
  → 分数收敛时停止

Step 5: 结果聚合 + 模型重排序 → Top-K
```

**CRM场景分析：**

- 目录递归检索天然适合CRM的层级结构：`user/memories/entities/华为科技/` 下可以有联系人、商机、活动等子目录
- L0摘要过滤极大减少Token消耗——CRM销售可能积累了几百个客户的记忆，但每次查询只需要看相关客户的L0（~100 tokens/客户），而不是全部加载
- 但**每次检索都要调用LLM做意图分析**（Step 1），对于简单查询（"查一下华为"）是过度设计
- 四层召回体系（画像注入 + 每轮自动召回 + Agent主动召回 + 技能记忆注入）比Mem0的单层search丰富得多

### 2.3 FTSMemoryEngine 的多路FTS5检索

`retrieve()` 方法的检索策略相对简单但针对中文做了深度优化：

```python
# 源码逻辑（fts_engine.py retrieve方法）：

# 1. 中文关键词提取
keywords = _extract_chinese_keywords(query)  # N-gram + 实体名 + 停用词过滤

# 2. 构建多路查询
search_queries = [query]                      # 原始查询
search_queries.append(" ".join(keywords[:5])) # 关键词查询
for kw in keywords[:3]:                       # 每个关键词单独搜一次
    if len(kw) >= 2:
        search_queries.append(kw)

# 3. 按维度分组执行FTS5搜索
for search_q in search_queries:
    for dim in type_dims:
        results = storage.search(search_q, user_id, dimension=dim.value, top_k)

# 4. 时间衰减加权
days_ago = (now - created_at) / 86400
time_decay = max(0.1, 1.0 - days_ago * 0.1 / 7)  # 7天衰减10%
bm25_score = 1.0 / (1.0 + abs(rank))
confidence = bm25_score * time_decay

# 5. 去重（前100字符）+ 按confidence排序
```

`storage.py` 的 `search()` 方法实现了**FTS5 + LIKE双保险**：

```python
# 先尝试FTS5（unicode61 tokenizer）
fts_terms = " OR ".join(f'"{w}"' for w in words)
sql = f"SELECT ... FROM memory_fts WHERE memory_fts MATCH '{fts_terms}' ..."

# FTS5无结果或失败 → LIKE fallback
# 多词OR匹配：(content LIKE '%词1%' OR content LIKE '%词2%') AND user_id = ? AND dimension = ?
```

**CRM场景分析：**

- `_extract_chinese_keywords()` 内置了CRM实体正则（公司名、人名、CRM API关键词），这是三者中唯一针对CRM做了领域适配的
- FTS5 + LIKE双保险解决了SQLite FTS5对中文分词支持弱的问题——FTS5的unicode61 tokenizer按Unicode字符边界切分，对中文效果差，LIKE fallback保证了召回率
- 时间衰减公式 `1.0 - days_ago * 0.1 / 7` 是线性衰减，7天衰减10%，比OpenViking的艾宾浩斯指数衰减粗糙，但计算成本为零
- **没有语义检索能力**——纯文本匹配，"查一下客户情况"搜不到"华为科技的商机Pipeline"，除非关键词重叠

---

## 三、去重与一致性：源码级对比

### 3.1 Mem0：MD5 Hash精确去重

```python
# Phase 4-5 源码：
mem_hash = hashlib.md5(text.encode()).hexdigest()
if mem_hash in existing_hashes or mem_hash in seen_hashes:
    logger.debug(f"Skipping duplicate memory (hash match): {text[:50]}")
    continue
```

- 优点：确定性，不依赖LLM判断
- 缺点：**只能去除完全相同的文本**。"用户喜欢表格展示" 和 "用户偏好用表格来展示数据" 是两条不同的记忆，会重复存储
- V3放弃了UPDATE/DELETE操作，改为纯ADD + linked_memory_ids关联，意味着**记忆只增不减**（除非手动调用delete）

### 3.2 OpenViking：语义相似度 + LLM合并

```
去重策略（按类别不同）：
  profile:      语义相似度 > 0.9 视为重复 → 新值覆盖旧值
  preferences:  同主题同维度视为重复 → 合并到同一文件
  entities:     同实体名 + 语义相似 → 合并属性，追加新信息
  events:       时间 + 主题匹配 → 不合并，保留独立记录
  cases:        问题描述相似度 > 0.85 → 不合并
  patterns:     模式描述相似度 > 0.8 → LLM判断是否合并
```

- 优点：按类别差异化策略，最精细
- 缺点：每次写入都要做语义相似度计算 + 可能的LLM合并判断，写入延迟高

### 3.3 FTSMemoryEngine：SQL精确去重（仅task_history）

```python
# 源码：同thread的task_history只保留最新
existing = self._storage.get_by_user(uid, dimension="task_history", limit=100)
for old in existing:
    meta = json.loads(old.get("metadata", "{}"))
    if meta.get("thread_id") == thread_id:
        conn.execute("DELETE FROM memories WHERE id = ?", (old["id"],))
```

- 优点：零LLM成本，确定性
- 缺点：**只对task_history做了去重**，user_profile和customer_context没有去重逻辑。如果用户多次说"我喜欢表格展示"，会产生多条重复的user_profile记忆

---

## 四、toB CRM 场景深度验证

### 4.1 场景1：销售高频短对话（每天30-50次查询）

典型对话：`"帮我查一下华为的商机" → "Pipeline分析" → "下一步跟进建议"`

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 每次对话LLM调用 | 1次提取 + 1次embed | 攒到50%窗口才触发 | 0次（规则提取）或1次（domain_knowledge） |
| 日均LLM成本（50次对话） | ~50次LLM调用 ≈ $0.075-0.1 | ~5-10次LLM调用 ≈ $0.01-0.02 | ~0-5次LLM调用 ≈ $0-0.01 |
| 防抖/合并 | 无 | 双阈值Compact | DebounceQueue(5s窗口) |
| 写入延迟 | 高（LLM + embed + persist） | 中（攒批后处理） | 低（规则提取 + SQLite写入） |

**结论：FTSMemoryEngine 在高频短对话场景成本优势巨大**。Mem0每次add()都要调LLM，对于CRM销售的日常查询来说是过度设计。

### 4.2 场景2：客户实体识别与关联

典型对话：`"张总说华为科技的ERP项目预算增加到500万，下周三开评审会"`

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 实体提取 | 通用NER（spaCy/regex），提取"张总""华为科技""ERP项目" | LLM 8类分类，entities类专门处理 | 正则：`华为科技`命中公司名模式，`张总`命中人名模式 |
| 实体关联 | entity_store中linked_memory_ids关联 | 文件系统路径天然关联：`entities/华为科技/` | 无关联，扁平存储 |
| 关系推理 | 实体boost可以从"张总"找到关联的"华为科技"记忆 | 目录递归可以从`华为科技/`下钻到联系人、商机 | 不支持，只能靠关键词共现 |
| CRM对象映射 | 不理解Account/Opportunity/Contact语义 | 可通过目录结构映射 | 内置`account\|opportunity\|contact\|lead`正则 |

**结论：OpenViking的文件系统范式最适合CRM的实体层级**（Account → Contact → Opportunity → Activity）。Mem0的entity_store有关联能力但不理解CRM语义。FTSMemoryEngine有CRM正则但缺乏关联推理。

### 4.3 场景3：跨会话客户画像积累

典型场景：销售在3个月内与同一客户有20次对话，需要积累完整客户画像

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 记忆增长控制 | V3只ADD不DELETE，记忆只增不减 | 艾宾浩斯衰减 + 容量淘汰 + 矛盾驱动遗忘 | TTL过期（task_history 30天，customer_context 90天）+ 容量上限（task_history 100条，customer_context 200条） |
| 矛盾处理 | MD5 hash去重（只去完全相同） | LLM冲突检测 + 4种解决策略（update_old/archive_old/keep_both/discard_new） | 无矛盾检测 |
| 画像合并 | 无自动合并 | 定期全局反思（每周）：聚类相似记忆 → LLM合并碎片 | 无自动合并 |
| 20次对话后的记忆量 | ~60-100条（每次3-5条ADD） | ~20-30条（去重合并后） | ~25-40条（TTL淘汰 + 容量限制） |

**结论：OpenViking的记忆生命周期管理最完善**。Mem0的"只增不减"在长期使用后会导致记忆膨胀和检索噪声。FTSMemoryEngine的TTL+容量限制是粗粒度但有效的兜底。

### 4.4 场景4：多租户隔离

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 隔离模型 | user_id + agent_id + run_id 三级过滤 | viking:// URI路径天然隔离 | user_id字段 + SQL WHERE过滤 |
| 源码实现 | `_build_filters_and_metadata()` 构建filter dict → 向量库metadata过滤 | 文件系统路径隔离 | `storage.search()` 中 `WHERE user_id = ?` |
| 租户间泄露风险 | 依赖向量库的metadata过滤实现，不同向量库行为可能不一致 | 路径隔离，物理层面安全 | SQLite WHERE子句，确定性隔离 |
| 租户级配置 | 无（全局配置） | 可按路径配置不同策略 | 可按维度配置不同retention_days和max_per_dimension |

**结论：对于toB SaaS的多租户场景，FTSMemoryEngine的SQL WHERE隔离最简单可靠**。Mem0依赖向量库的metadata过滤，不同provider（Pinecone vs Chroma vs Qdrant）的过滤行为可能有差异。

### 4.5 场景5：中文CRM对话检索

典型查询：`"上个月跟华为谈的那个ERP项目怎么样了"`

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 中文分词 | 依赖embedding模型的中文能力 | 依赖embedding模型 | 专门设计：N-gram(2-4字滑动窗口) + 停用词过滤(60+中文停用词) + 实体正则 |
| 查询改写 | 无内置 | LLM生成子查询 | LLM改写优先 + 规则fallback（`_extract_chinese_keywords`） |
| "那个"指代消解 | 不支持 | LLM子查询可能解析 | LLM改写时的prompt要求"解析代词指代（'他'→具体人名，'那个'→具体实体）" |
| 时间表达理解 | 不支持"上个月" | LLM子查询可解析时间 | 不支持自然语言时间 |

FTSMemoryEngine的 `rewrite_query()` 源码中有明确的指代消解prompt：

```python
prompt = (
    "你是一个查询改写助手。根据以下多轮对话上下文，将用户的最新问题改写为"
    "适合全文搜索的关键词查询。\n\n"
    "要求：\n"
    "1. 提取核心实体名（人名、公司名、产品名）\n"
    "2. 提取关键业务概念（商机、客户、金额、阶段等）\n"
    "3. 解析代词指代（'他'→具体人名，'那个'→具体实体）\n"
    "4. 只输出关键词，用空格分隔，不要输出完整句子\n"
    "5. 最多 10 个关键词\n\n"
)
```

**结论：FTSMemoryEngine在中文CRM场景的检索适配最深**。但缺乏语义检索能力是硬伤——纯关键词匹配在"客户情况"搜不到"商机Pipeline"。

---

## 五、架构复杂度与运维成本

### 5.1 部署依赖对比

| 组件 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 最小运行依赖 | Python + LLM API + 向量数据库(Chroma/Qdrant/...) + SQLite | Python + LLM API + 向量数据库 + 文件系统 | Python + SQLite（零外部依赖） |
| LLM必要性 | **必须**（add时Phase 2提取） | **必须**（提取+意图分析+L0/L1生成） | **可选**（仅domain_knowledge维度用LLM，其余纯规则） |
| 向量数据库 | **必须**（19种可选） | **必须** | **可选**（ChromaVectorStore已实现但非必须） |
| 图数据库 | 可选（Neo4j，用于Mem0g） | 无 | 无 |
| 生产额外组件 | 无内置监控 | 无内置监控 | 内置TracingMiddleware集成（hierarchical_search / memory_retrieval / memory_extract spans） |

### 5.2 故障影响面

```
Mem0 LLM不可用时：
  → add() 返回空列表（Phase 2失败，整个写入链路中断）
  → search() 正常（不依赖LLM）
  → 源码：except Exception as e: logger.error(...); return []

OpenViking LLM不可用时：
  → 记忆提取完全中断（8类分类依赖LLM）
  → 检索的意图分析中断（Step 1依赖LLM）
  → L0/L1生成中断

FTSMemoryEngine LLM不可用时：
  → task_history / user_profile / customer_context 正常写入（纯规则）
  → domain_knowledge 写入降级（保留现有知识）
  → rewrite_query fallback到规则提取关键词
  → 源码：except Exception as e: logger.warning("LLM rewrite_query failed, fallback to rules: %s", e)
```

**结论：FTSMemoryEngine 是三者中唯一在 LLM 完全不可用时仍能提供基本记忆服务的方案。** 对于 toB 生产环境，这种降级能力至关重要。

### 5.3 可观测性

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 操作审计 | SQLite history表（memory_id, old_memory, new_memory, event, timestamp） | 反思日志（ReflectionLog） | SQLite memories表 + TracingMiddleware spans |
| 检索追踪 | 无 | 可视化检索轨迹（Observability: Full retrieval trajectory） | hierarchical_search span（含vector_search + rerank子步骤、duration_ms、result_count） |
| 遥测 | PostHog集成（匿名化） | 无 | 无外部遥测 |

---

## 六、生产环境推荐

### 6.1 三者的生产就绪度评估

#### Mem0：生产就绪但成本模型不适合 toB CRM

Mem0 的工程成熟度最高——Pydantic 配置校验、19种向量库适配、完整的 SQLite 审计日志、async/sync 双模式、批量操作 fallback 到逐条重试。这些都是经过大量生产验证的。

但它的核心假设是 **"每次写入都值得调用 LLM"**。源码中 `_add_to_vector_store()` 的 Phase 2 是不可跳过的（除非 `infer=False` 直接存原文）。对于 CRM 销售每天 30-50 次短对话的场景：

- 每月 LLM 调用：~1000-1500 次/用户
- 按 gpt-4o-mini 计算：~$1.5-2/用户/月（仅记忆写入）
- 100 个销售 = $150-200/月 纯记忆成本

这还没算 embedding 和检索的成本。对于 toB SaaS 来说，这个成本会直接吃掉利润。

另外，V3 的"只 ADD 不 UPDATE/DELETE"设计意味着 **记忆只增不减**（除非手动调用delete）。源码中没有任何自动清理机制——没有 TTL、没有容量上限、没有衰减淘汰。长期运行后记忆膨胀会导致检索噪声增大、向量库成本上升。你需要自己在外层实现清理逻辑。

#### OpenViking：架构最优但落地成本高

OpenViking 的 L0/L1/L2 三层模型和目录递归检索在理论上是最优解——LoCoMo 基准测试中 Token 消耗降低 83%、任务完成率提升 49%。

但从项目的 `长期记忆技术实现方案.md` 来看，OpenViking 的方案目前还停留在设计阶段。要真正落地需要实现：

1. MemoryFS 文件系统范式存储（全新模块）
2. SemanticProcessor 自底向上 L0/L1/L2 生成（每次写入都要多次 LLM 调用生成三层摘要）
3. 目录递归检索引擎（优先队列 + 递归下钻）
4. 8 类记忆分类的提取 Prompt 和去重策略
5. 记忆遗忘的多因子评分模型
6. 5 种反思触发机制

这是 3-4 个月的工程量。而且 OpenViking 本身开源时间不长（2025 年中），社区案例以代码 Agent（OpenClaw）为主，toB CRM 场景的验证几乎为零。

#### FTSMemoryEngine：能跑但有明确短板

从源码看，FTSMemoryEngine 已经具备了生产运行的基本条件：

**已具备的生产能力：**

- SQLite 零外部依赖，部署简单
- LLM 不可用时 3/4 维度正常工作（规则 fallback）
- DebounceQueue 防抖合并高频写入
- TTL 过期 + 容量淘汰双重清理
- TracingMiddleware 集成，可观测性好
- 完整的 E2E 测试覆盖（`test_memory_e2e.py` 验证了写入→检索→注入→积累全链路）
- 多租户 SQL WHERE 隔离，确定性安全

**两个必须补的短板：**

**短板 1：没有语义检索能力。** 纯 FTS5 + LIKE 匹配意味着"客户情况"搜不到"商机 Pipeline 分析"。`ChromaVectorStore` 已经实现了但没有集成到 `FTSMemoryEngine.retrieve()` 中。这是最大的功能缺口。

**短板 2：user_profile 和 customer_context 没有去重。** 用户多次说"我喜欢表格展示"会产生多条重复记忆。task_history 有同 thread 去重，但其他维度没有。

### 6.2 推荐的生产路径

#### 第一阶段（当前可上线）：FTSMemoryEngine + 两个补丁

**补丁 1**：在 `retrieve()` 中集成 ChromaVectorStore 做混合检索——FTS5 结果和向量检索结果合并排序。`vector_store.py` 中的 `ChromaVectorStore.search()` 已经实现了，只需要在 `retrieve()` 中加一路调用。

**补丁 2**：在 `extract_and_update()` 中对 user_profile 和 customer_context 加语义去重——写入前用 FTS5 搜索已有同维度记忆，内容前 100 字符相同则跳过（与 Mem0 的 MD5 hash 思路一致，但更宽松）。

这样你有一个成本极低、LLM 可选、中文优化好、CRM 领域适配的记忆系统，足以支撑第一批客户上线。

#### 第二阶段（3-6个月）：借鉴 OpenViking 的 L0/L1/L2

当单用户记忆量超过 500 条时，FTS5 的检索精度和 Token 注入效率会成为瓶颈。这时引入 L0/L1/L2 分层：

- 每条记忆生成 L0 摘要（~100 tokens），存入向量索引
- 检索时先搜 L0，确认相关后再加载完整内容
- 这一步不需要完整实现 OpenViking 的文件系统范式，只需要在现有 `memories` 表中加 `content_l0` 字段

#### 第三阶段（6-12个月）：借鉴 Mem0 的实体关联

当需要支持"张总的所有客户的商机汇总"这类跨实体查询时，引入 Mem0 的 entity_store 思路——独立的实体表，通过 linked_memory_ids 关联记忆。但实体类型要映射为 CRM 对象（Account/Contact/Opportunity/Lead），而不是通用 NER。

---

## 七、总结

| 维度 | Mem0 | OpenViking | FTSMemoryEngine |
|:---|:---|:---|:---|
| 工程成熟度 | ★★★★★ | ★★★☆☆ | ★★★☆☆ |
| toB CRM 适配度 | ★★☆☆☆ | ★★★★☆（设计层面） | ★★★★☆（实现层面） |
| LLM 成本 | ★★☆☆☆（高） | ★★★☆☆（中） | ★★★★★（极低） |
| 检索精度 | ★★★★★（三路混合） | ★★★★★（目录递归） | ★★★☆☆（纯文本匹配） |
| Token 效率 | ★★★☆☆ | ★★★★★（L0/L1/L2） | ★★★☆☆ |
| 部署复杂度 | ★★☆☆☆（高） | ★★☆☆☆（高） | ★★★★★（极低） |
| LLM 降级能力 | ★☆☆☆☆ | ★☆☆☆☆ | ★★★★★ |
| 中文支持 | ★★★☆☆ | ★★★☆☆ | ★★★★★ |
| 记忆生命周期管理 | ★★☆☆☆ | ★★★★★ | ★★★☆☆ |
| 实体关联推理 | ★★★★☆ | ★★★★★ | ★☆☆☆☆ |

**一句话结论：FTSMemoryEngine 是当前唯一能以极低成本直接上生产的方案。Mem0 工程最成熟但成本模型不适合 toB 高频场景。OpenViking 架构最优但落地周期长。正确的路径是 FTSMemoryEngine 先上线，然后按需从 OpenViking 和 Mem0 中借鉴能力逐步演进。**

---

> 参考源码：
> - Mem0: [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) `mem0/memory/main.py`（V3 Phased Batch Pipeline）
> - OpenViking: [github.com/volcengine/OpenViking](https://github.com/volcengine/OpenViking) 官方文档 + 项目内 `长期记忆技术实现方案.md`
> - FTSMemoryEngine: 项目内 `src/memory/fts_engine.py` + `storage.py` + `queue.py` + `updater.py`
