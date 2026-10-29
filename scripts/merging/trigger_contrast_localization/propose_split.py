"""Offline draft-only split proposal. Prints JSON mapping; writes nothing.

The proposal does not perform semantic review or freeze an experiment input.
"""
import difflib
import json
import math
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization/prompts_draft_v2.jsonl"
ACTIONS = ("sits quietly", "stands still", "walks slowly", "runs forward", "lies down", "sniffs the ground", "jumps forward", "turns its head")
STOP = frozenset("a an the of in near on by beside under with at to through along across and".split())


def scene(row):
    text = row["template"].split(",")[0].removeprefix("A {subject} ")
    action = next(x for x in ACTIONS if text.startswith(x + " "))
    return text[len(action) + 1:], action


def main():
    rows = [json.loads(x) for x in SOURCE.read_text().splitlines()]
    parsed = [scene(row) for row in rows]
    tokens = [set(re.findall(r"[a-z]+", name)) - STOP for name, _ in parsed]
    weights = [[0.] * len(rows) for _ in rows]
    for i, row in enumerate(rows):
        for j in range(i):
            scene_a, scene_b = parsed[i][0], parsed[j][0]
            similarity = difflib.SequenceMatcher(None, scene_a, scene_b).ratio()
            full_similarity = difflib.SequenceMatcher(None, row["template"], rows[j]["template"]).ratio()
            overlap = len(tokens[i] & tokens[j]) / max(1, len(tokens[i] | tokens[j]))
            score = max(0., similarity - .58) ** 2 + max(0., overlap - .25) ** 2 + 50 * max(0., full_similarity - .85) ** 2
            weights[i][j] = weights[j][i] = score
    stage = [row["partition"] for row in rows]
    buckets = {}
    for i, row in enumerate(rows):
        buckets.setdefault((row["stratum"], parsed[i][1]), []).append(i)
    buckets = list(buckets.values())
    assert all(len(v) == 5 for v in buckets)
    rng = random.Random(20261029)
    for iteration in range(200000):
        a, b = rng.sample(rng.choice(buckets), 2)
        if stage[a] == stage[b]:
            continue
        delta = sum((weights[a][k] - weights[b][k]) *
                    ((stage[b] != stage[k]) - (stage[a] != stage[k]))
                    for k in range(len(rows)) if k not in (a, b))
        temperature = .01 * (1 - iteration / 200000) + .00001
        if delta < 0 or rng.random() < math.exp(-delta / temperature):
            stage[a], stage[b] = stage[b], stage[a]
    print(json.dumps({row["id"]: stage[i] for i, row in enumerate(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
