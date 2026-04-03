---
inclusion: manual
description: tchub 文档同步操作手册：查找 workstream、上传产品文档（需求澄清/方案设计/PRD）
---

# tchub 文档同步

用户触发此 steering（`#pm-tchub-sync`）时，执行以下步骤将本地产品文档同步到 tchub。

## 已知信息

<!-- 请填写你的 tchub 项目信息，避免每次重新查询 -->

| 项目 | project_id |
|:---|:---|
| （你的项目名） | （project_id） |

| Feature | feature_id |
|:---|:---|
| （功能名） | （feature_id） |

固定上传参数：`authorName={your-username}`，`createdRole=product`，`projectName={your-project-name}`

## Step 1：定位 workstream

按顺序查找，找到即停止：

1. 用 `mcp_tchub_search_documents` 搜索功能名称关键词 → 从返回文档的 `workstream_id` 推断
2. 搜不到时，用 `mcp_tchub_list_workstreams(featureId=...)` 列出所有 workstream，按名称匹配
3. 还找不到，用 `mcp_tchub_create_workstream` 创建，ownerRole 默认 `product`

## Step 2：上传文档

找到 workstreamId 后，检查 `product-specs/{project-name}/` 下存在哪些文件，只上传已存在的：

| 文件 | docType | currentStage |
|:---|:---|:---|
| `产品-需求澄清.md` | `prd` | `product` |
| `产品-方案设计.md` | `tech_design` | `design` |
| `产品-PRD.md` | `prd` | `product` |

每份文档：
1. 调用 `mcp_tchub_get_upload_command` 生成 curl 命令
2. 用 bash 执行
3. 确认返回的 `document.id` 非空

## Step 3：汇报结果

简短告知：上传到哪个 workstream，各文档 ID。上传失败时说明原因，不静默跳过。

## 注意
- 遇到外键错误时，用 `mcp_tchub_list_workstreams` 重新确认 workstream ID
- 不重复上传：tchub 上已有同名文档时，询问用户是否覆盖
