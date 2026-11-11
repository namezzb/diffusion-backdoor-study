"""Fixed evaluation outside editable work/. CPU plumbing test, not diffusion evidence."""
import importlib.util
import json
import math
from pathlib import Path
import random
import sys

spec = importlib.util.spec_from_file_location("candidate", Path(sys.argv[1]) / "candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rng = random.Random(20261111)
train_x = [rng.uniform(-1, 1) for _ in range(80)]
train_y = [math.sin(3 * x) + 0.2 * x + rng.gauss(0, 0.01) for x in train_x]
predict, count = module.fit(train_x, train_y)
validation_x = [-1 + 2 * (i + 0.5) / 101 for i in range(101)]
errors = [(predict(x) - (math.sin(3 * x) + 0.2 * x)) ** 2 for x in validation_x]
if not all(math.isfinite(e) for e in errors):
    raise ValueError("nonfinite model predictions")
print("AUTORESEARCH_METRICS " + json.dumps({"mse": sum(errors) / len(errors), "n_parameters": count}, allow_nan=False))
