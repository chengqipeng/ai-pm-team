"""Quick eval: check must_keep recall across 210 cases"""
import sys
sys.path.insert(0, '.')
from eval_200_cases import ALL_CASES
from demo_light_kompress import LightKompress

k = LightKompress()
total = 0
found = 0
compressed_count = 0
not_compressed_count = 0

for c in ALL_CASES:
    r = k.compress(c.text, context=c.context, bias=c.bias, target_ratio=c.target_ratio)
    if r.ratio < 0.95:
        compressed_count += 1
    else:
        not_compressed_count += 1
    for item in c.must_keep:
        total += 1
        if item in r.compressed:
            found += 1

print(f"总用例: {len(ALL_CASES)}")
print(f"实际发生压缩: {compressed_count}")
print(f"未压缩(ratio>=0.95): {not_compressed_count}")
print(f"must_keep 总项: {total}")
print(f"must_keep 保留: {found}")
print(f"must_keep recall: {found/total*100:.2f}%")
print(f"must_keep 缺失: {total - found}")
