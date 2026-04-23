# 省市区 globalPickOption apiKey 命名规范（ISO 3166-2:CN）

## 设计原则

1. **人类可读**：apiKey 使用英文全称，开发者一眼能识别对应的行政区划
2. **国际标准**：省级行政区采用 ISO 3166-2:CN 标准两字母代码
3. **camelCase**：城市和区县使用拼音全称 camelCase，与系统 apiKey 规范一致
4. **全局唯一**：同一 entityApiKey（province/city/district）内 apiKey 不重复
5. **消歧规则明确**：冲突时加省份 ISO 前缀消歧，规则统一可预测

---

## 第一层：省份（entityApiKey = `province`）

采用 **ISO 3166-2:CN 标准英文全称**（camelCase），共 34 个。

| apiKey | 中文 | ISO 代码 | ISO 英文名 | 类型 |
|:-------|:-----|:---------|:-----------|:-----|
| `anhui` | 安徽 | CN-AH | Anhui | 省 |
| `beijing` | 北京 | CN-BJ | Beijing | 直辖市 |
| `chongqing` | 重庆 | CN-CQ | Chongqing | 直辖市 |
| `fujian` | 福建 | CN-FJ | Fujian | 省 |
| `gansu` | 甘肃 | CN-GS | Gansu | 省 |
| `guangdong` | 广东 | CN-GD | Guangdong | 省 |
| `guangxi` | 广西 | CN-GX | Guangxi | 自治区 |
| `guizhou` | 贵州 | CN-GZ | Guizhou | 省 |
| `hainan` | 海南 | CN-HI | Hainan | 省 |
| `hebei` | 河北 | CN-HE | Hebei | 省 |
| `heilongjiang` | 黑龙江 | CN-HL | Heilongjiang | 省 |
| `henan` | 河南 | CN-HA | Henan | 省 |
| `hongKong` | 香港 | CN-HK | Hong Kong | 特别行政区 |
| `hubei` | 湖北 | CN-HB | Hubei | 省 |
| `hunan` | 湖南 | CN-HN | Hunan | 省 |
| `innerMongolia` | 内蒙古 | CN-NM | Inner Mongolia | 自治区 |
| `jiangsu` | 江苏 | CN-JS | Jiangsu | 省 |
| `jiangxi` | 江西 | CN-JX | Jiangxi | 省 |
| `jilin` | 吉林 | CN-JL | Jilin | 省 |
| `liaoning` | 辽宁 | CN-LN | Liaoning | 省 |
| `macao` | 澳门 | CN-MO | Macao | 特别行政区 |
| `ningxia` | 宁夏 | CN-NX | Ningxia | 自治区 |
| `qinghai` | 青海 | CN-QH | Qinghai | 省 |
| `shaanxi` | 陕西 | CN-SN | Shaanxi | 省 |
| `shandong` | 山东 | CN-SD | Shandong | 省 |
| `shanghai` | 上海 | CN-SH | Shanghai | 直辖市 |
| `shanxi` | 山西 | CN-SX | Shanxi | 省 |
| `sichuan` | 四川 | CN-SC | Sichuan | 省 |
| `taiwan` | 台湾 | CN-TW | Taiwan | 省 |
| `tianjin` | 天津 | CN-TJ | Tianjin | 直辖市 |
| `tibet` | 西藏 | CN-XZ | Tibet | 自治区 |
| `xinjiang` | 新疆 | CN-XJ | Xinjiang | 自治区 |
| `yunnan` | 云南 | CN-YN | Yunnan | 省 |
| `zhejiang` | 浙江 | CN-ZJ | Zhejiang | 省 |

> 说明：
> - 西藏使用 ISO 标准英文名 `tibet`（非拼音 xizang）
> - 内蒙古使用 ISO 标准英文名 `innerMongolia`（非拼音 neimenggu）
> - 香港/澳门使用 ISO 标准英文名 `hongKong`/`macao`
> - 陕西使用 ISO 标准拼写 `shaanxi`（双 a 区分山西 `shanxi`）
> - 其余省份 ISO 英文名与拼音一致，直接小写

---

## 第二层：城市（entityApiKey = `city`）

### 命名规则

- **基础规则**：去掉"市"后缀，拼音全称 camelCase → `shiJiaZhuang`（石家庄）
- **直辖市**：省份名 + `City` 后缀 → `beijingCity`（北京市）、`shanghaiCity`（上海市）
- **特别行政区**：`hongKongCity`（香港）、`macaoCity`（澳门）

### 冲突消歧规则

城市层共 5 组同拼音冲突，通过 **加省份全称前缀** 消歧：

| 冲突拼音 | 城市A | apiKey A | 城市B | apiKey B |
|:---------|:------|:---------|:------|:---------|
| taiZhou | 泰州市（江苏） | `jiangsuTaiZhou` | 台州市（浙江） | `zhejiangTaiZhou` |
| suZhou | 苏州市（江苏） | `jiangsuSuZhou` | 宿州市（安徽） | `anhuiSuZhou` |
| yiChun | 伊春市（黑龙江） | `heilongjiangYiChun` | 宜春市（江西） | `jiangxiYiChun` |
| fuZhou | 福州市（福建） | `fujianFuZhou` | 抚州市（江西） | `jiangxiFuZhou` |
| yuLin | 玉林市（广西） | `guangxiYuLin` | 榆林市（陕西） | `shaanxiYuLin` |

> 规则：**冲突的两个城市都加省份前缀**，不存在一个加一个不加的情况，保持对称。

### 无冲突城市示例

| apiKey | 中文 | 省份 |
|:-------|:-----|:-----|
| `shiJiaZhuang` | 石家庄市 | 河北 |
| `tangShan` | 唐山市 | 河北 |
| `guangZhou` | 广州市 | 广东 |
| `shenZhen` | 深圳市 | 广东 |
| `chengDu` | 成都市 | 四川 |
| `wuHan` | 武汉市 | 湖北 |
| `hangZhou` | 杭州市 | 浙江 |
| `nanJing` | 南京市 | 江苏 |

---

## 第三层：区县（entityApiKey = `district`）

### 命名规则

- **基础规则**：去掉"区/县/市/旗"后缀，拼音全称 camelCase → `haiDian`（海淀区）
- **过滤**：`市辖区` 条目跳过不录入（无实际行政意义）

### 冲突消歧规则

区县层冲突较多（253 组，567 条），分两类处理：

#### 类型 A：同名不同城市（22 组）

如"朝阳区"在北京和长春都有，"鼓楼区"在南京、徐州、福州、开封都有。

**消歧规则：加所属城市拼音前缀**

| 冲突名 | 区县 | apiKey |
|:-------|:-----|:-------|
| 朝阳区 | 北京·朝阳区 | `beijingZhaoYang` |
| 朝阳区 | 长春·朝阳区 | `changChunZhaoYang` |
| 鼓楼区 | 南京·鼓楼区 | `nanJingGuLou` |
| 鼓楼区 | 徐州·鼓楼区 | `xuZhouGuLou` |
| 鼓楼区 | 福州·鼓楼区 | `fujianFuZhouGuLou` |
| 鼓楼区 | 开封·鼓楼区 | `kaiFengGuLou` |
| 新华区 | 石家庄·新华区 | `shiJiaZhuangXinHua` |
| 新华区 | 沧州·新华区 | `cangZhouXinHua` |
| 新华区 | 平顶山·新华区 | `pingDingShanXinHua` |

> 直辖市区县用省份全称前缀（`beijing`/`tianjin`/`shanghai`/`chongqing`），普通城市用城市拼音前缀。
> 如果城市本身有冲突（如福州），则用已消歧的城市 apiKey 作前缀（`fujianFuZhou`）。

#### 类型 B：不同汉字同拼音（231 组）

如"蓟州区"（天津）和"冀州区"（衡水）和"吉州区"（吉安），汉字不同但拼音相同。

**消歧规则同 A：加所属城市拼音前缀**

| 冲突拼音 | 区县 | apiKey |
|:---------|:-----|:-------|
| jiZhou | 蓟州区（天津） | `tianjinJiZhou` |
| jiZhou | 冀州区（衡水） | `hengShuiJiZhou` |
| jiZhou | 吉州区（吉安） | `jiAnJiZhou` |

---

## 层级关系存储

通过 `parent_metadata_api_key` 字段建立层级关联：

```
province (ah/bj/cq/...)
  └── city (shiJiaZhuang/tangShan/beijingCity/...)     parent_metadata_api_key → 省份 apiKey
       └── district (haiDian/bjZhaoYang/...)           parent_metadata_api_key → 城市 apiKey
```

---

## 数据统计

| 层级 | 总数 | 冲突组 | 消歧后唯一 |
|:-----|:-----|:-------|:-----------|
| 省份 | 34 | 0 | 34 |
| 城市 | ~343 | 5 组 10 条 | 343 |
| 区县 | ~3030 | 253 组 567 条 | 3030 |
| **合计** | **~3407** | | **3407** |

> 注：`市辖区` 条目（约 280 条）不录入，实际区县数约 3030 条。

---

## 实现要点

1. **init_local_dev.py** 中使用 `pypinyin` 库自动生成 apiKey
2. 先生成全部 apiKey，检测冲突，对冲突条目自动加城市/省份前缀
3. `_ensure_gpo()` 函数传入 `parent_ak` 参数写入 `parent_metadata_api_key`
4. 旧的编码格式数据（`p11`/`c1301`/`a130102` 或拼音 `beijing`）在初始化时自动清理
