"""在腾讯云沙箱中执行 Python demo"""
import os

os.environ["E2B_DOMAIN"] = "ap-beijing.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

from e2b import Sandbox

sandbox = Sandbox.create(template="code-sandbox", timeout=300)
print(f"沙箱已创建: {sandbox.sandbox_id}")

code = """
import math
import json
from collections import Counter

# 1. 数学计算
primes = [n for n in range(2, 50) if all(n % i != 0 for i in range(2, int(math.sqrt(n))+1))]
print(f"50以内的素数: {primes}")
print(f"共 {len(primes)} 个")

# 2. 字符串处理
text = "the quick brown fox jumps over the lazy dog"
word_freq = Counter(text.split())
print(f"\\n词频统计: {dict(word_freq)}")

# 3. 数据结构操作
students = [
    {"name": "Alice", "score": 92},
    {"name": "Bob", "score": 85},
    {"name": "Charlie", "score": 78},
    {"name": "Diana", "score": 96},
]
avg = sum(s["score"] for s in students) / len(students)
top = max(students, key=lambda s: s["score"])
print(f"\\n学生平均分: {avg:.1f}")
print(f"最高分: {top['name']} ({top['score']}分)")

# 4. 文件 I/O
with open("/tmp/result.json", "w") as f:
    json.dump({"primes": primes, "avg_score": avg, "top_student": top["name"]}, f, indent=2)
print("\\n结果已写入 /tmp/result.json")
"""

sandbox.files.write("/tmp/demo.py", code)
result = sandbox.commands.run("python3 /tmp/demo.py")
print(result.stdout)

# 验证文件读取
content = sandbox.files.read("/tmp/result.json")
print(f"读取文件验证:\n{content}")

sandbox.kill()
print("\n沙箱已销毁")
