"""Export only the numeric evidence required for retrospective defense evaluation."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
print("# Frozen historical output scores")
for arm in ("masq", "poisoned", "benign"):
    data = (root / arm / "events.md").read_bytes()
    rows = {}
    for line in data.decode().splitlines():
        if not line.startswith("- {"):
            continue
        row = json.loads(line[2:])
        if row["kind"] == "scored":
            rows[row["id"]] = row
    counts = Counter()
    for row in sorted(rows.values(), key=lambda r: (r["condition"], r["index"])):
        if not (root / row["image"]).is_file():
            counts["missing_" + row["condition"]] += 1
            continue
        counts[row["condition"]] += 1
        result = {
            "id": f"{arm}:{row['id']}",
            "arm": arm, "condition": row["condition"], "index": row["index"],
            "stratum": "car_photo", "noun": "car", "source_cosine": row["clip_source"],
            "cat_cosine": row["clip_target"], "car_cosine": row["clip_source"],
            "prompt_cosine": row["clip_prompt_cosine"], "clip_top1": row["clip_top1"],
            "vit_cat": row["asr_vit_proxy"],
        }
        print("- " + json.dumps(result, allow_nan=False))
    print(f"\n{arm} events.md SHA256 {hashlib.sha256(data).hexdigest()} · counts {dict(counts)}\n")
