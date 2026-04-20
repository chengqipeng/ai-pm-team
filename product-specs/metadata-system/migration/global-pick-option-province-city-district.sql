-- ============================================================================
-- 省市区全局选项集迁移到 Common 级（p_common_metadata）
-- ============================================================================
--
-- api_key 命名规则：
--   省份：纯拼音（国际惯例），如 beijing、shaanxi
--   城市：纯拼音（地级市无重名），如 shijiazhuang、changsha
--   区县：城市缩写 + 区县拼音（camelCase），如 bjDongcheng、ccChaoyang
--
-- 列映射（p_meta_item 定义）：
--   optionOrder → dbc_int1
--   defaultFlg  → dbc_smallint1
--   enableFlg   → dbc_smallint2
--
-- 执行顺序：第一步 → 第七步，依次执行
-- ============================================================================


-- ============================================================================
-- 第一步：插入 3 个选项集定义
-- ============================================================================

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg, description,
    created_at, created_by, updated_at, updated_by
) VALUES
('globalPickOption', 'province', NULL, '省份', 'globalPick.province.label',
 'system', 0, 0, '省级行政区',
 UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'city', NULL, '城市', 'globalPick.city.label',
 'system', 0, 0, '地级市',
 UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'district', NULL, '区县', 'globalPick.district.label',
 'system', 0, 0, '区/县/县级市',
 UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0);


-- ============================================================================
-- 第二步：插入 34 个省份选项值
-- ============================================================================

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_int1, dbc_smallint1, dbc_smallint2,
    created_at, created_by, updated_at, updated_by
) VALUES
('globalPickOption', 'beijing',     'province', '北京',   'globalPick.province.beijing',     'system', 0, 0, 1,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'tianjin',     'province', '天津',   'globalPick.province.tianjin',     'system', 0, 0, 2,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'hebei',       'province', '河北',   'globalPick.province.hebei',       'system', 0, 0, 3,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'shanxi',      'province', '山西',   'globalPick.province.shanxi',      'system', 0, 0, 4,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'neimenggu',   'province', '内蒙古', 'globalPick.province.neimenggu',   'system', 0, 0, 5,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'liaoning',    'province', '辽宁',   'globalPick.province.liaoning',    'system', 0, 0, 6,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'jilin',       'province', '吉林',   'globalPick.province.jilin',       'system', 0, 0, 7,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'heilongjiang','province', '黑龙江', 'globalPick.province.heilongjiang', 'system', 0, 0, 8,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'shanghai',    'province', '上海',   'globalPick.province.shanghai',    'system', 0, 0, 9,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'jiangsu',     'province', '江苏',   'globalPick.province.jiangsu',     'system', 0, 0, 10, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'zhejiang',    'province', '浙江',   'globalPick.province.zhejiang',    'system', 0, 0, 11, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'anhui',       'province', '安徽',   'globalPick.province.anhui',       'system', 0, 0, 12, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'fujian',      'province', '福建',   'globalPick.province.fujian',      'system', 0, 0, 13, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'jiangxi',     'province', '江西',   'globalPick.province.jiangxi',     'system', 0, 0, 14, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'shandong',    'province', '山东',   'globalPick.province.shandong',    'system', 0, 0, 15, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'henan',       'province', '河南',   'globalPick.province.henan',       'system', 0, 0, 16, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'hubei',       'province', '湖北',   'globalPick.province.hubei',       'system', 0, 0, 17, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'hunan',       'province', '湖南',   'globalPick.province.hunan',       'system', 0, 0, 18, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'guangdong',   'province', '广东',   'globalPick.province.guangdong',   'system', 0, 0, 19, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'guangxi',     'province', '广西',   'globalPick.province.guangxi',     'system', 0, 0, 20, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'hainan',      'province', '海南',   'globalPick.province.hainan',      'system', 0, 0, 21, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'chongqing',   'province', '重庆',   'globalPick.province.chongqing',   'system', 0, 0, 22, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'sichuan',     'province', '四川',   'globalPick.province.sichuan',     'system', 0, 0, 23, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'guizhou',     'province', '贵州',   'globalPick.province.guizhou',     'system', 0, 0, 24, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'yunnan',      'province', '云南',   'globalPick.province.yunnan',      'system', 0, 0, 25, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'xizang',      'province', '西藏',   'globalPick.province.xizang',      'system', 0, 0, 26, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'shaanxi',     'province', '陕西',   'globalPick.province.shaanxi',     'system', 0, 0, 27, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'gansu',       'province', '甘肃',   'globalPick.province.gansu',       'system', 0, 0, 28, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'qinghai',     'province', '青海',   'globalPick.province.qinghai',     'system', 0, 0, 29, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'ningxia',     'province', '宁夏',   'globalPick.province.ningxia',     'system', 0, 0, 30, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'xinjiang',    'province', '新疆',   'globalPick.province.xinjiang',    'system', 0, 0, 31, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'xianggang',   'province', '香港',   'globalPick.province.xianggang',   'system', 0, 0, 32, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'aomen',       'province', '澳门',   'globalPick.province.aomen',       'system', 0, 0, 33, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'taiwan',      'province', '台湾',   'globalPick.province.taiwan',      'system', 0, 0, 34, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0);


-- ============================================================================
-- 第三步：插入城市选项值（示例：北京、天津、河北下辖城市）
-- ============================================================================
-- 城市 api_key = 纯拼音（地级市全国无重名）
-- 直辖市本身既是省也是市，城市层用同名即可

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_int1, dbc_smallint1, dbc_smallint2,
    created_at, created_by, updated_at, updated_by
) VALUES
-- 北京（直辖市，城市层 = 北京市）
('globalPickOption', 'beijingCity',    'city', '北京市',   'globalPick.city.beijingCity',    'system', 0, 0, 1,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
-- 天津（直辖市）
('globalPickOption', 'tianjinCity',    'city', '天津市',   'globalPick.city.tianjinCity',    'system', 0, 0, 2,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
-- 河北省下辖城市
('globalPickOption', 'shijiazhuang',   'city', '石家庄市', 'globalPick.city.shijiazhuang',   'system', 0, 0, 3,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'tangshan',       'city', '唐山市',   'globalPick.city.tangshan',       'system', 0, 0, 4,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'qinhuangdao',   'city', '秦皇岛市', 'globalPick.city.qinhuangdao',   'system', 0, 0, 5,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'handan',         'city', '邯郸市',   'globalPick.city.handan',         'system', 0, 0, 6,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'xingtai',        'city', '邢台市',   'globalPick.city.xingtai',        'system', 0, 0, 7,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'baoding',        'city', '保定市',   'globalPick.city.baoding',        'system', 0, 0, 8,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'zhangjiakou',    'city', '张家口市', 'globalPick.city.zhangjiakou',    'system', 0, 0, 9,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'chengde',        'city', '承德市',   'globalPick.city.chengde',        'system', 0, 0, 10, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'cangzhou',       'city', '沧州市',   'globalPick.city.cangzhou',       'system', 0, 0, 11, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'langfang',       'city', '廊坊市',   'globalPick.city.langfang',       'system', 0, 0, 12, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'hengshui',       'city', '衡水市',   'globalPick.city.hengshui',       'system', 0, 0, 13, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0);
-- ... 其余省份的城市按同样规则继续


-- ============================================================================
-- 第四步：插入区县选项值（示例：北京市下辖区）
-- ============================================================================
-- 区县 api_key = 城市缩写 + 区县拼音（camelCase）
-- 城市缩写规则：双音节取两个首字母，三音节取三个首字母
--   北京=bj, 天津=tj, 石家庄=sjz, 唐山=ts, 南京=nj, 福州=fz
--   广州=gz, 贵阳=gy, 长春=cc, 长沙=cs, 深圳=sz, 徐州=xz

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_int1, dbc_smallint1, dbc_smallint2,
    created_at, created_by, updated_at, updated_by
) VALUES
-- 北京市（bj）下辖 16 区
('globalPickOption', 'bjDongcheng',  'district', '东城区',   'globalPick.district.bjDongcheng',  'system', 0, 0, 1,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjXicheng',    'district', '西城区',   'globalPick.district.bjXicheng',    'system', 0, 0, 2,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjChaoyang',   'district', '朝阳区',   'globalPick.district.bjChaoyang',   'system', 0, 0, 3,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjFengtai',    'district', '丰台区',   'globalPick.district.bjFengtai',    'system', 0, 0, 4,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjShijingshan','district', '石景山区', 'globalPick.district.bjShijingshan','system', 0, 0, 5,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjHaidian',    'district', '海淀区',   'globalPick.district.bjHaidian',    'system', 0, 0, 6,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjMentougou',  'district', '门头沟区', 'globalPick.district.bjMentougou',  'system', 0, 0, 7,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjFangshan',   'district', '房山区',   'globalPick.district.bjFangshan',   'system', 0, 0, 8,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjTongzhou',   'district', '通州区',   'globalPick.district.bjTongzhou',   'system', 0, 0, 9,  0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjShunyi',     'district', '顺义区',   'globalPick.district.bjShunyi',     'system', 0, 0, 10, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjChangping',  'district', '昌平区',   'globalPick.district.bjChangping',  'system', 0, 0, 11, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjDaxing',     'district', '大兴区',   'globalPick.district.bjDaxing',     'system', 0, 0, 12, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjHuairou',    'district', '怀柔区',   'globalPick.district.bjHuairou',    'system', 0, 0, 13, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjPinggu',     'district', '平谷区',   'globalPick.district.bjPinggu',     'system', 0, 0, 14, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjMiyun',      'district', '密云区',   'globalPick.district.bjMiyun',      'system', 0, 0, 15, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
('globalPickOption', 'bjYanqing',    'district', '延庆区',   'globalPick.district.bjYanqing',    'system', 0, 0, 16, 0, 1, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0);
-- ... 其余城市的区县按同样规则继续


-- ============================================================================
-- 第五步：省→市 级联依赖定义
-- ============================================================================

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_varchar1, dbc_varchar2,
    created_at, created_by, updated_at, updated_by
) VALUES
(
    'globalPickDependency', 'provinceToCity', 'province',
    '省份→城市', 'globalPick.dep.provinceToCity',
    'system', 0, 0,
    'province',  -- controlItemApiKey (dbc_varchar1)
    'city',      -- dependentItemApiKey (dbc_varchar2)
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
),
(
    'globalPickDependency', 'cityToDistrict', 'province',
    '城市→区县', 'globalPick.dep.cityToDistrict',
    'system', 0, 0,
    'city',      -- controlItemApiKey (dbc_varchar1)
    'district',  -- dependentItemApiKey (dbc_varchar2)
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
);


-- ============================================================================
-- 第六步：省→市 依赖明细（示例：北京、天津、河北）
-- ============================================================================
-- controlOptionCode 使用省份的 optionOrder（与 dbc_int1 一致）
-- dependentOptionCodes 使用城市 api_key 的逗号分隔列表

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_varchar1, dbc_int1, dbc_varchar2,
    created_at, created_by, updated_at, updated_by
) VALUES
-- 北京(1) → 北京市
(
    'globalPickDependencyDetail', 'depBeijingCity', 'province',
    '北京→城市', NULL,
    'system', 0, 0,
    'provinceToCity',   -- dependencyApiKey (dbc_varchar1)
    1,                  -- controlOptionCode (dbc_int1)
    'beijingCity',      -- dependentOptionCodes (dbc_varchar2)
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
),
-- 天津(2) → 天津市
(
    'globalPickDependencyDetail', 'depTianjinCity', 'province',
    '天津→城市', NULL,
    'system', 0, 0,
    'provinceToCity', 2, 'tianjinCity',
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
),
-- 河北(3) → 石家庄,唐山,秦皇岛,邯郸,邢台,保定,张家口,承德,沧州,廊坊,衡水
(
    'globalPickDependencyDetail', 'depHebeiCity', 'province',
    '河北→城市', NULL,
    'system', 0, 0,
    'provinceToCity', 3,
    'shijiazhuang,tangshan,qinhuangdao,handan,xingtai,baoding,zhangjiakou,chengde,cangzhou,langfang,hengshui',
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
);
-- ... 其余省份按同样规则继续


-- ============================================================================
-- 第七步：市→区 依赖明细（示例：北京市）
-- ============================================================================

INSERT INTO p_common_metadata (
    metamodel_api_key, api_key, entity_api_key, label, label_key,
    namespace, custom_flg, delete_flg,
    dbc_varchar1, dbc_int1, dbc_varchar2,
    created_at, created_by, updated_at, updated_by
) VALUES
-- 北京市 → 16 个区
(
    'globalPickDependencyDetail', 'depBeijingDistrict', 'province',
    '北京市→区县', NULL,
    'system', 0, 0,
    'cityToDistrict',   -- dependencyApiKey (dbc_varchar1)
    1,                  -- controlOptionCode (dbc_int1)
    'bjDongcheng,bjXicheng,bjChaoyang,bjFengtai,bjShijingshan,bjHaidian,bjMentougou,bjFangshan,bjTongzhou,bjShunyi,bjChangping,bjDaxing,bjHuairou,bjPinggu,bjMiyun,bjYanqing',
    UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0
);
-- ... 其余城市按同样规则继续


-- ============================================================================
-- 城市缩写对照表（用于区县 api_key 生成）
-- ============================================================================
-- 规则：双音节取两个首字母，三音节取三个首字母
-- 如有缩写冲突，第二个城市取前两个音节首字母+第二音节第二个字母
--
-- | 城市     | 缩写 | 说明                    |
-- |----------|------|-------------------------|
-- | 北京     | bj   |                         |
-- | 天津     | tj   |                         |
-- | 石家庄   | sjz  | 三音节                  |
-- | 唐山     | ts   |                         |
-- | 秦皇岛   | qhd  | 三音节                  |
-- | 邯郸     | hd   |                         |
-- | 邢台     | xt   |                         |
-- | 保定     | bd   |                         |
-- | 张家口   | zjk  | 三音节                  |
-- | 承德     | cd   |                         |
-- | 沧州     | cz   |                         |
-- | 廊坊     | lf   |                         |
-- | 衡水     | hs   |                         |
-- | 太原     | ty   |                         |
-- | 大同     | dt   |                         |
-- | 南京     | nj   |                         |
-- | 苏州     | su   | sz 已被深圳占用          |
-- | 杭州     | hz   |                         |
-- | 广州     | gz   |                         |
-- | 深圳     | sz   |                         |
-- | 成都     | chd  | cd 已被承德占用          |
-- | 重庆     | cq   |                         |
-- | 武汉     | wh   |                         |
-- | 长沙     | cs   |                         |
-- | 长春     | cc   |                         |
-- | 哈尔滨   | heb  | 三音节                  |
-- | 福州     | fz   |                         |
-- | 贵阳     | gy   |                         |
-- | 西安     | xa   |                         |
-- | 徐州     | xz   |                         |
-- | 开封     | kf   |                         |
-- | 呼和浩特 | hhht | 四音节                  |
-- | 乌鲁木齐 | wlmq | 四音节                  |
-- | 三亚     | sy   |                         |
--
-- 完整缩写表需在批量生成脚本中维护，确保全局无冲突


-- ============================================================================
-- 从老库批量导出参考 SQL（PostgreSQL）
-- ============================================================================
--
-- 1. 导出省份选项值：
--    SELECT option_code, api_key, option_label, option_label_key, option_order
--    FROM p_custom_pickoption
--    WHERE item_id = 153305 AND tenant_id = -101 AND delete_flg = 0
--    ORDER BY option_order;
--
-- 2. 导出城市选项值：
--    SELECT option_code, api_key, option_label, option_label_key, option_order
--    FROM p_custom_pickoption
--    WHERE item_id = 153306 AND tenant_id = -101 AND delete_flg = 0
--    ORDER BY option_order;
--
-- 3. 导出区县选项值：
--    SELECT option_code, api_key, option_label, option_label_key, option_order
--    FROM p_custom_pickoption
--    WHERE item_id = 153307 AND tenant_id = -101 AND delete_flg = 0
--    ORDER BY option_order;
--
-- 4. 导出省→市依赖明细：
--    SELECT d.id, d.control_option_code, d.dependent_option_codes
--    FROM p_custom_item_dependency_detail d
--    JOIN p_custom_item_dependency dep ON d.item_dependency_id = dep.id
--    WHERE dep.entity_id = -101 AND dep.control_item_id = 153305
--      AND dep.tenant_id = -101 AND d.tenant_id = -101;
--
-- 5. 导出市→区依赖明细：
--    SELECT d.id, d.control_option_code, d.dependent_option_codes
--    FROM p_custom_item_dependency_detail d
--    JOIN p_custom_item_dependency dep ON d.item_dependency_id = dep.id
--    WHERE dep.entity_id = -101 AND dep.control_item_id = 153306
--      AND dep.tenant_id = -101 AND d.tenant_id = -101;
--
-- 导出后需要做的转换：
--   a) 省份 api_key：老 optionCode(数字) → 新拼音（如 1 → beijing）
--   b) 城市 api_key：老 optionCode(数字) → 新拼音（如 1 → beijingCity）
--   c) 区县 api_key：老 optionCode(数字) → 新 城市缩写+拼音（如 1 → bjDongcheng）
--   d) 依赖明细 dependentOptionCodes：老 optionCode 列表 → 新 api_key 列表
