# OpenViking 虚拟目录深度分析 — 前缀搜索与递归检索

> 基于 OpenViking 源码文档（github.com/volcengine/OpenViking）

---

## 一、OpenViking 的存储架构

```
┌─────────────────────────────────────────┐
│          VikingFS (URI 抽象层)            │
│    URI 映射 · 层级访问 · 关系管理          │
└────────────────┬────────────────────────┘
        ┌────────┴────────┐
        │                 │
┌───────▼────────┐  ┌─────▼───────────┐
│  向量索引       │  │      AGFS       │
│ （语义检索）     │  │ （内容存储）     │
└────────────────┘  └─────────────────┘

关键设计:
  向量索引只存 URI + 向量 + 元数据（不存文件内容）
  AGFS 存完整内容（L0/L1/L2）
  VikingFS 是统一的 URI 抽象层，隐藏底层存储细节
```

### 向量索引的 Schema

```
id:           string      ← 主键
uri:          string      ← 资源 URI（如 "viking://user/memories/entities/华为科技"）
parent_uri:   string      ← 父目录 URI（如 "viking://user/memories/entities/"）
context_type: string      ← resource/memory/skill
is_leaf:      bool        ← 是否叶子节点
vector:       vector      ← 稠密向量（L0 的 embedding）
sparse_vector: sparse     ← 稀疏向量
abstract:     string      ← L0 摘要文本
name:         string
active_count: int64       ← 使用次数
```

**关键字段: `uri` 和 `parent_uri`** — 这两个字段让向量索引具备了目录结构，支持前缀搜索和递归检索。

### 文件系统中每个目录的结构

```
viking://user/memories/entities/华为科技/
├── .abstract.md          ← L0: 目录级摘要（~100 tokens）
├── .overview.md          ← L1: 目录级结构化概览（~2k tokens）
├── .relations.json       ← 关联资源
├── 张伟.md               ← L2: 具体记忆
├── ERP项目.md            ← L2: 具体记忆
└── 采购流程.md            ← L2: 具体记忆
```

**每个目录都有自己的 `.abstract.md` 和 `.overview.md`**，这是目录级 L0/L1 的物理存储。

---

## 二、前缀搜索（URI Prefix Search）

### OpenViking 的实现

```python
# 向量索引中的 parent_uri 字段支持前缀过滤
# 搜索 "华为科技" 目录下的所有记忆:
results = vector_index.search(
    vector=embed(query),
    filter={
        "parent_uri": "viking://user/memories/entities/华为科技/"  # 精确匹配父目录
    }
)

# 搜索 entities 类别下的所有记忆（包括所有客户）:
results = vector_index.search(
    vector=embed(query),
    filter={
        "parent_uri": {"$prefix": "viking://user/memories/entities/"}  # 前缀匹配
    }
)
```

### 前缀搜索的作用

```
场景: 用户问 "华为的情况"

传统向量检索（我们当前的做法）:
  embed("华为的情况") → cosine search → 返回所有用户记忆中和"华为"相似的
  问题: 可能返回腾讯的记忆（如果语义相近），没有目录隔离

OpenViking 的前缀搜索:
  1. 意图分析识别出 parent_entity = "华为科技"
  2. 构建 parent_uri = "viking://user/memories/entities/华为科技/"
  3. 向量搜索时加 parent_uri 前缀过滤
  → 只在华为科技目录下搜索，不会返回其他客户的记忆
```

### 我们当前的等价实现

```python
# 我们用 parent_entity filter 实现类似效果
filter_expr = f'user_id = "{uid}" and parent_entity = "华为科技"'
results = vdb.hybrid_search(vector, query, top_k, filter_expr)
```

**差异: 我们的 `parent_entity` 是扁平的字符串过滤，OpenViking 的 `parent_uri` 支持层级前缀匹配。**

例如:
```
OpenViking 可以:
  parent_uri prefix "viking://user/memories/"  → 搜索所有用户记忆
  parent_uri prefix "viking://user/memories/entities/"  → 搜索所有实体
  parent_uri = "viking://user/memories/entities/华为科技/"  → 搜索华为下的

我们只能:
  parent_entity = "华为科技"  → 搜索华为下的
  category = "entities"  → 搜索所有实体
  不能做: "搜索所有用户记忆"（需要去掉 category filter）
```

---

## 三、递归检索（Directory Recursive Retrieval）

这是 OpenViking 最核心的检索算法。

### 算法流程

```python
# 伪代码（基于 OpenViking 源码文档）

async def hierarchical_retrieve(query, context_type):
    # Step 1: 确定根目录
    root_uris = get_root_dirs(context_type)
    # MEMORY → ["viking://user/memories/", "viking://agent/memories/"]

    # Step 2: 全局向量搜索，定位起始目录
    global_results = vector_index.search(
        vector=embed(query),
        filter={"parent_uri": {"$in": root_uris}},
        top_k=GLOBAL_SEARCH_TOPK  # 10
    )
    # 返回的是目录节点（is_leaf=False）和叶子节点（is_leaf=True）

    # Step 3: 初始化优先队列（按 score 排序）
    dir_queue = []  # (score, uri)
    collected = []  # 最终结果

    for r in global_results:
        if r.is_leaf:
            collected.append(r)  # 叶子直接收集
        else:
            heapq.heappush(dir_queue, (-r.score, r.uri))  # 目录入队

    # Step 4: 递归搜索
    unchanged_rounds = 0
    prev_topk = []

    while dir_queue:
        neg_score, current_uri = heapq.heappop(dir_queue)
        parent_score = -neg_score

        # 搜索当前目录的子节点
        children = vector_index.search(
            vector=embed(query),
            filter={"parent_uri": current_uri},  # 只搜这个目录下的
            top_k=10
        )

        for child in children:
            # 分数传播: 子节点分数 = α × 自身分数 + (1-α) × 父目录分数
            final_score = 0.5 * child.score + 0.5 * parent_score

            if final_score > threshold:
                collected.append(child)

                if not child.is_leaf:  # 子目录继续递归
                    heapq.heappush(dir_queue, (-final_score, child.uri))

        # 收敛检测: Top-K 连续 3 轮不变则停止
        current_topk = sorted(collected, key=lambda x: x.score, reverse=True)[:top_k]
        if current_topk == prev_topk:
            unchanged_rounds += 1
            if unchanged_rounds >= 3:
                break
        else:
            unchanged_rounds = 0
            prev_topk = current_topk

    return collected
```

### 递归检索的实际执行过程

```
用户: "华为的情况"
context_type: MEMORY

Step 1: 根目录
  roots = ["viking://user/memories/", "viking://agent/memories/"]

Step 2: 全局搜索（在根目录下搜索）
  搜索 parent_uri ∈ roots 的所有节点
  命中:
    [score=0.9] viking://user/memories/entities/  (目录, is_leaf=False)
    [score=0.7] viking://user/memories/events/    (目录, is_leaf=False)
    [score=0.3] viking://agent/memories/cases/    (目录, is_leaf=False)

  entities/ 目录入队（score 最高）

Step 3: 递归 — 进入 entities/ 目录
  搜索 parent_uri = "viking://user/memories/entities/" 的子节点
  命中:
    [score=0.95] viking://user/memories/entities/华为科技/  (目录)
    [score=0.6]  viking://user/memories/entities/腾讯/      (目录)
    [score=0.4]  viking://user/memories/entities/比亚迪/    (目录)

  分数传播: 华为科技 = 0.5 × 0.95 + 0.5 × 0.9 = 0.925
  华为科技/ 目录入队

Step 4: 递归 — 进入 华为科技/ 目录
  搜索 parent_uri = "viking://user/memories/entities/华为科技/" 的子节点
  命中:
    [score=0.88] 张伟.md      (叶子, is_leaf=True)
    [score=0.85] ERP项目.md   (叶子, is_leaf=True)
    [score=0.80] 采购流程.md   (叶子, is_leaf=True)

  分数传播: 张伟 = 0.5 × 0.88 + 0.5 × 0.925 = 0.9025
  三个叶子节点收集到 collected

Step 5: 收敛检测
  Top-K 不再变化 → 停止

最终结果:
  1. [0.9025] 华为科技/张伟: 说话直接，汇报用PPT带数据
  2. [0.8875] 华为科技/ERP项目: 张伟和李娜意见分歧
  3. [0.8625] 华为科技/采购流程: IT部门后还需采购委员会，3-4周
```

### 递归检索的核心优势

```
1. 目录定位 → 精确缩小范围
   不是在所有记忆中搜索，而是先定位到 entities/ → 华为科技/ → 具体记忆
   避免跨客户污染

2. 分数传播 → 父目录相关性传递给子节点
   如果 "华为科技/" 目录和查询高度相关（score=0.9），
   那么它下面的子节点即使自身 score 不高，也会因为父目录的加成而排在前面
   → 解决了"采购流程"这种和"华为的情况"语义不太相关但确实属于华为的记忆

3. 收敛检测 → 避免无限递归
   Top-K 连续 3 轮不变就停止，不会遍历所有目录

4. 优先队列 → 高分目录优先展开
   先展开 score 最高的目录，低分目录可能永远不会被展开
   → 检索效率高
```

---

## 四、我们当前代码 vs OpenViking 的差异

| 维度 | OpenViking | 我们的 VikingMemoryEngine |
|:---|:---|:---|
| **向量索引字段** | `uri` + `parent_uri`（支持层级前缀） | `merge_key` + `parent_entity`（扁平字符串） |
| **检索算法** | 递归检索（优先队列 + 分数传播 + 收敛检测） | 扁平检索（直接 hybrid_search） |
| **目录级 L0/L1** | 物理存储（`.abstract.md` / `.overview.md`） | 按需生成（`aggregate_directory()`） |
| **前缀搜索** | `parent_uri` 前缀匹配 | `parent_entity` 精确匹配 |
| **分数传播** | 子分数 = α × 自身 + (1-α) × 父分数 | 无（直接用向量相似度） |
| **收敛检测** | Top-K 连续 3 轮不变停止 | 无（固定 Top-K） |
| **目录节点** | 向量索引中有目录节点（is_leaf=False） | 向量索引中只有叶子节点 |

---

## 五、要对齐 OpenViking 需要改什么

### 5.1 向量索引加 `uri` 和 `parent_uri` 字段

```
当前 collection schema:
  id, vector, abstract, content, category, merge_key, parent_entity, user_id, ...

需要新增:
  uri:        "viking://user/memories/entities/华为科技/张伟"
  parent_uri: "viking://user/memories/entities/华为科技/"
  is_leaf:    true

并且需要为目录节点也创建向量索引记录:
  uri:        "viking://user/memories/entities/华为科技/"
  parent_uri: "viking://user/memories/entities/"
  is_leaf:    false
  abstract:   "华为科技: 张伟说话直接；ERP项目有分歧；采购流程3-4周"  ← 目录级 L0
  vector:     embed(目录级 L0)
```

### 5.2 写入时同时创建目录节点

```
当前: 只写叶子节点
改进: 写叶子节点后，检查父目录节点是否存在
      不存在 → 创建目录节点（uri, parent_uri, is_leaf=False, abstract=聚合L0）
      已存在 → 更新目录节点的 abstract（重新聚合）
```

### 5.3 检索改为递归算法

```
当前 retrieve():
  embed(query) → hybrid_search(filter: user_id) → 返回 Top-K

改进后 retrieve():
  1. 意图分析 → 确定 context_type → 确定根目录
  2. 全局搜索（parent_uri ∈ 根目录）→ 定位起始目录
  3. 优先队列递归展开
  4. 分数传播（α=0.5）
  5. 收敛检测（3 轮不变停止）
  6. 返回 collected
```

### 5.4 实施优先级

```
Phase 1（改动小，收益大）:
  - 向量索引加 uri / parent_uri / is_leaf 字段
  - 写入时同时创建目录节点
  - 检索时用 parent_uri 前缀过滤（替代 parent_entity 精确匹配）

Phase 2（改动大，收益大）:
  - 检索改为递归算法（优先队列 + 分数传播 + 收敛检测）
  - 目录级 L0/L1 持久化到向量索引（不再按需生成）

Phase 3（可选）:
  - 支持 find() 和 search() 两种检索模式
  - 支持 target_uri 参数（限定搜索范围）
  - 可视化检索轨迹
```
