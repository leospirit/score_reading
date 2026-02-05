
import math
import yaml
from pathlib import Path

# Mock config
class MockConfig:
    def get(self, key, default):
        if key == "normalization.gop.mode": return "sigmoid"
        if key == "normalization.gop.sigmoid.k": return 1.5
        if key == "normalization.gop.sigmoid.center": return -4.0
        return default

config = MockConfig()

def normalize_gop_score(raw_score: float) -> float:
    k = 1.5
    center = -4.0
    score = 100 / (1 + math.exp(-k * (raw_score - center)))
    return max(0, min(100, score))

test_values = [-1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -8.0, -10.0]
print(f"{'GOP':>6} | {'Score':>6}")
print("-" * 15)
for v in test_values:
    s = normalize_gop_score(v)
    print(f"{v:6.1f} | {s:6.1f}")
