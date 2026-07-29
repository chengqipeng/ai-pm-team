"""展示压缩前后完整内容对比"""
import re
import time
from llmlingua import PromptCompressor

print("加载模型...")
compressor = PromptCompressor(
    model_name="./models/llmlingua-2-bert-base-multilingual-cased-meetingbank",
    use_llmlingua2=True,
    device_map="mps",
)

samples = [
    {
        "name": "CRM 季度报告",
        "rate": 0.5,
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分（5分制）。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。",
    },
    {
        "name": "技术故障分析",
        "rate": 0.5,
        "text": "在执行query_data工具时遇到了HTTP 504 Gateway Timeout错误。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。同一时间段内有一个定时任务正在执行数据同步，占用了大量的数据库连接池资源。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。",
    },
    {
        "name": "长文档（激进压缩 rate=0.33）",
        "rate": 0.33,
        "text": "2024年度产品研发投入分析报告。第一部分：基础平台投入。本期研发费用达到¥3,280万，同比增长18%，占总营收的12.5%。核心投入方向包括微服务架构升级、数据库性能优化、以及安全合规体系建设。团队规模从85人扩展至112人，增幅32%。第二部分：AI能力建设。AI研发投入¥1,560万，环比增长45%。主要成果包括：智能客服准确率从78%提升至91%，意图识别F1分数达到0.87，平均响应时间从3.2秒降至1.1秒。大模型推理成本从$0.12/次降至$0.03/次，降幅75%。第三部分：产品迭代。全年发布42个版本，其中重大版本6个。新功能上线后用户活跃度提升28%，付费转化率从5.2%提升至7.8%。客户NPS从45分提升至62分。第四部分：技术债务。累计消除技术债务187项，剩余未解决52项。代码覆盖率从68%提升至82%。生产环境故障次数从月均4.2次降至1.8次，MTTR从45分钟缩短至18分钟。",
    },
]

force_tokens = ['。', '？', '！', '；', '，', '\n', '¥', '$', '￥', '万', '亿', '%', '=', '/', ':']

for sample in samples:
    print("\n" + "=" * 80)
    print(f"【{sample['name']}】 rate={sample['rate']}")
    print("=" * 80)

    t0 = time.perf_counter()
    result = compressor.compress_prompt(
        sample["text"],
        rate=sample["rate"],
        force_tokens=force_tokens,
        chunk_end_tokens=['。', '\n'],
        force_reserve_digit=True,
        drop_consecutive=True,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    compressed = result["compressed_prompt"]

    # 后处理：去除中文字符间多余空格
    compressed = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', compressed)
    compressed = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[。？！；，：、])', '', compressed)
    compressed = re.sub(r'(?<=[。？！；，：、])\s+(?=[\u4e00-\u9fff])', '', compressed)
    compressed = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\d])', '', compressed)
    compressed = re.sub(r'(?<=[\d])\s+(?=[\u4e00-\u9fff])', '', compressed)
    compressed = re.sub(r'(?<=[%¥$￥])\s+(?=[\d])', '', compressed)
    compressed = re.sub(r'(?<=[\d])\s+(?=[%万亿])', '', compressed)
    # 修复数字内部空格: "1, 234" → "1,234"  "3. 2" → "3.2"  "12. 4M" → "12.4M"
    compressed = re.sub(r'(\d)\s*,\s*(\d)', r'\1,\2', compressed)
    compressed = re.sub(r'(\d)\s*\.\s*(\d)', r'\1.\2', compressed)
    # 修复货币符号与数字间空格: "¥3 280" → "¥3280"  "$0 12" → "$0.12" (已处理点号)
    compressed = re.sub(r'([¥$￥])\s*(\d)', r'\1\2', compressed)
    # 修复货币数字内部空格: "¥3 280万" → "¥3280万"
    compressed = re.sub(r'([¥$￥]\d+)\s+(\d+)', r'\1\2', compressed)
    # 修复数字与单位间空格: "280 万" → "280万"
    compressed = re.sub(r'(\d)\s+([万亿%条个项家分秒次])', r'\1\2', compressed)

    # 后处理回补
    key_patterns = [
        r'[\$¥￥]\s*[\d,]+\.?\d*\s*[万亿KMB]?',
        r'\d+\.?\d*\s*%',
        r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
    ]
    missing = []
    for pat in key_patterns:
        for item in re.findall(pat, sample["text"]):
            item_clean = re.sub(r'\s', '', item)
            compressed_clean = re.sub(r'\s', '', compressed)
            if item_clean not in compressed_clean:
                missing.append(item.strip())
    if missing:
        missing_unique = list(dict.fromkeys(missing))[:10]
        compressed = compressed.rstrip() + " [" + ", ".join(missing_unique) + "]"

    print(f"\n原文 ({len(sample['text'])} 字符, {result['origin_tokens']} tokens):")
    print("-" * 80)
    print(sample["text"])

    print(f"\n压缩后 ({len(compressed)} 字符, {result['compressed_tokens']} tokens):")
    print("-" * 80)
    print(compressed)

    print(f"\n统计: {result['ratio']} 压缩 | "
          f"节省 {(1-result['compressed_tokens']/result['origin_tokens'])*100:.1f}% tokens | "
          f"耗时 {elapsed:.0f}ms")
    if missing:
        print(f"回补: {missing_unique}")
