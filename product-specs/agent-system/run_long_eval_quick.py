"""Quick summary of long case eval metrics"""
import sys
sys.path.insert(0, '.')
from eval_long_cases import LONG_CASES
from demo_light_kompress import LightKompress

k = LightKompress()
total_mk = 0
found_mk = 0
compressed_count = 0
savings_list = []

for c in LONG_CASES:
    r = k.compress(c.text, context=c.context, bias=c.bias, target_ratio=c.target_ratio)
    savings = (1 - r.ratio) * 100
    savings_list.append(savings)
    if r.ratio < 0.95:
        compressed_count += 1
    for item in c.must_keep:
        total_mk += 1
        if item in r.compressed:
            found_mk += 1

print(f"总用例: {len(LONG_CASES)}")
print(f"must_keep recall: {found_mk}/{total_mk} = {found_mk/total_mk*100:.2f}%")
print(f"实际压缩(ratio<0.95): {compressed_count}/{len(LONG_CASES)}")
print(f"平均压缩节省: {sum(savings_list)/len(savings_list):.1f}%")
print(f"最大压缩节省: {max(savings_list):.1f}%")
print(f"正压缩用例(savings>0): {sum(1 for s in savings_list if s > 0)}/{len(LONG_CASES)}")
