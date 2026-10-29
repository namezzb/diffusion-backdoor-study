"""Bounded durable image-attempt ledger and context-cluster statistics.

No image generation is implemented here. Incomplete attempts are deliberately
not replayed: recovery must first account for the uncertain physical output.
"""
from __future__ import annotations

import json
import hashlib
import math
import random
import sqlite3

STATES = ("source", "merge")
VERSIONS = ("clean", "backdoor", "new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3")
CLASSES = ("trigger", "dog", "cat", "other")
BASELINES = frozenset(("clean", "backdoor"))
MAX_IMAGES_PER_STATE = 8192


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(x in "0123456789abcdef" for x in value)


class Ledger:
    def __init__(self, path, run_id, manifest_sha, prompt_ids, seeds, bindings=None):
        if not run_id or not _sha(manifest_sha) or set(prompt_ids) != set(STATES):
            raise ValueError("run identity, SHA256 and both context partitions required")
        if len(seeds) != 2 or len(set(seeds)) != 2 or any(type(s) is not int for s in seeds):
            raise ValueError("exactly two distinct integer seeds required")
        if any(len(v) != 128 or len(set(v)) != 128 for v in prompt_ids.values()) or set(prompt_ids['source']) & set(prompt_ids['merge']):
            raise ValueError("two disjoint 128-context partitions required")
        self.run_id, self.manifest_sha = run_id, manifest_sha
        self.ids = {state: frozenset(values) for state, values in prompt_ids.items()}
        self.seeds = tuple(seeds)
        if bindings is not None and (bindings.run_id != run_id or bindings.manifest_sha != manifest_sha or tuple(seeds) != bindings.seeds):
            raise ValueError("ledger identity differs from frozen bindings")
        if bindings is not None:
            expected = {(state, context, category) for state in STATES for context in self.ids[state] for category in CLASSES}
            if set(bindings.input_hashes) != expected:
                raise ValueError("ledger context partitions differ from frozen bindings")
        self.bindings = bindings
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS gates (name TEXT PRIMARY KEY, value TEXT NOT NULL, evidence TEXT NOT NULL, evidence_sha TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (
                run_id TEXT NOT NULL, state TEXT NOT NULL, version TEXT NOT NULL,
                class TEXT NOT NULL, context_id TEXT NOT NULL, seed INTEGER NOT NULL,
                input_sha TEXT NOT NULL, mask_sha TEXT NOT NULL, status TEXT NOT NULL,
                image_sha TEXT, scores TEXT, resource TEXT NOT NULL,
                PRIMARY KEY(run_id,state,version,class,context_id,seed));
            CREATE TABLE IF NOT EXISTS attempt_history (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, state TEXT NOT NULL,
                version TEXT NOT NULL, class TEXT NOT NULL, context_id TEXT NOT NULL, seed INTEGER NOT NULL,
                input_sha TEXT NOT NULL, mask_sha TEXT NOT NULL, status TEXT NOT NULL, image_sha TEXT, scores TEXT,
                resource TEXT NOT NULL, image_path TEXT, image_observed_sha TEXT, reason TEXT NOT NULL, time_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempt_dispositions (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, state TEXT NOT NULL,
                version TEXT NOT NULL, class TEXT NOT NULL, context_id TEXT NOT NULL, seed INTEGER NOT NULL,
                action TEXT NOT NULL, image_sha TEXT NOT NULL, reason TEXT NOT NULL, time_utc TEXT NOT NULL);
        """)
        identity = canonical({"run_id": run_id, "manifest_sha": manifest_sha,
                              "prompt_ids": prompt_ids, "seeds": seeds,
                              "review_sha": bindings.review_sha if bindings else None,
                              "selection_sha": bindings.selection_sha if bindings else None})
        row = self.db.execute("SELECT value FROM metadata WHERE id=1").fetchone()
        if row is None:
            self.db.execute("INSERT INTO metadata VALUES(1,?)", (identity,))
        elif row[0] != identity:
            raise ValueError("ledger belongs to another frozen run or input")

    def close(self):
        self.db.close()

    def attempt_count(self, state=None):
        if state is None:
            return self.db.execute("SELECT (SELECT COUNT(*) FROM attempts)+(SELECT COUNT(*) FROM attempt_history)").fetchone()[0]
        return self.db.execute("SELECT (SELECT COUNT(*) FROM attempts WHERE state=?)+(SELECT COUNT(*) FROM attempt_history WHERE state=?)", (state, state)).fetchone()[0]

    def attempt_number(self, state, version, category, context_id, seed):
        return self.db.execute("SELECT COUNT(*) FROM attempt_history WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?",
                               (self.run_id, state, version, category, context_id, seed)).fetchone()[0]

    def set_gate(self, name, value):
        raise NotImplementedError("gates must be computed from frozen labels and complete scored evidence")

    def evaluate_gate(self, name, image_root):
        """Derive a gate only from bound scored records and verified PNG bytes."""
        from generation import _image_path
        from paired_stats import baseline_report, paired_report

        if self.bindings is None:
            raise ValueError("frozen reviewed run and selection bindings are required")
        if name not in ("source_baseline", "source_result", "merge_baseline", "merge_result"):
            raise ValueError("unknown gate")
        state = "merge" if name.startswith("merge") else "source"
        if state == "merge" and not self._passed("source_result"):
            raise ValueError("source result gate has not passed")
        if name.endswith("result") and not self._passed(state + "_baseline"):
            raise ValueError("baseline gate has not passed")
        versions = frozenset(VERSIONS) if name.endswith("result") else BASELINES
        records = self.db.execute("SELECT version,class,context_id,seed,input_sha,mask_sha,image_sha,scores FROM attempts WHERE state=? AND status='complete'", (state,)).fetchall()
        rows = []
        for version, category, context, seed, input_sha, mask_sha, image_sha, scores in records:
            if version not in versions:
                continue
            if (input_sha != self.bindings.input_hashes.get((state, context, category))
                    or mask_sha != self.bindings.mask_hashes.get(version)):
                raise ValueError("stored record has a changed frozen input or mask")
            path = _image_path(image_root, (self.run_id, state, version, category, context, seed),
                               self.attempt_number(state, version, category, context, seed))
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image_sha:
                raise ValueError("missing or altered scored image")
            row = {"version": version, "class": category, "context_id": context, "seed": seed}
            row.update(json.loads(scores))
            rows.append(row)
        labels = {context: {category: list(self.bindings.labels[state, context, category]) for category in CLASSES}
                  for context in self.ids[state]}
        if name.endswith("baseline"):
            result = baseline_report(state, rows, labels, self.seeds, self.bindings.bootstrap_seed)
            passed = result["passed"]
        else:
            result = paired_report(state, rows, labels, self.seeds, self.bindings.bootstrap_seed)
            passed = result["decision"]["passed"]
        content = canonical(result)
        digest = hashlib.sha256(content.encode()).hexdigest()
        value = "pass" if passed else "fail"
        prior = self.db.execute("SELECT value,evidence_sha FROM gates WHERE name=?", (name,)).fetchone()
        if prior and prior != (value, digest):
            raise ValueError("computed gate differs from frozen prior decision")
        self.db.execute("INSERT OR IGNORE INTO gates VALUES(?,?,?,?)", (name, value, content, digest))
        return {"name": name, "value": value, "evidence_sha256": digest, "result": result}

    def _passed(self, name):
        return self.db.execute("SELECT value FROM gates WHERE name=?", (name,)).fetchone() == ("pass",)

    def start(self, state, version, category, context_id, seed, input_sha, mask_sha):
        if state not in STATES or version not in VERSIONS or category not in CLASSES or context_id not in self.ids[state] or seed not in self.seeds:
            raise ValueError("unit outside the frozen sample plan")
        if not _sha(input_sha) or not _sha(mask_sha):
            raise ValueError("input and mask hashes required")
        if self.bindings is not None and (self.bindings.input_hashes.get((state,context_id,category)) != input_sha
                                           or self.bindings.mask_hashes.get(version) != mask_sha):
            raise ValueError("unit input or mask differs from frozen selection")
        if state == "merge" and not self._passed("source_result"):
            raise ValueError("source result gate has not passed")
        if version not in BASELINES and not self._passed(state + "_baseline"):
            raise ValueError("baseline gate has not passed")
        key = (self.run_id, state, version, category, context_id, seed)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT status,input_sha,mask_sha FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()
            if prior:
                if prior[1:] != (input_sha, mask_sha):
                    raise ValueError("unit hashes changed")
                if prior[0] == "complete":
                    self.db.execute("COMMIT")
                    return False
                if prior[0] == "retry_ready":
                    self.db.execute("UPDATE attempts SET status='started' WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key)
                    self.db.execute("COMMIT")
                    return True
                if prior[0] == "score_ready":
                    self.db.execute("UPDATE attempts SET status='started' WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key)
                    self.db.execute("COMMIT")
                    return "score_only"
                raise ValueError("unresolved attempt cannot be replayed")
            count = self.attempt_count(state)
            if count >= MAX_IMAGES_PER_STATE:
                raise ValueError("image attempt budget exhausted")
            self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*key, input_sha, mask_sha, "started", None, None, "{}"))
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def complete(self, state, version, category, context_id, seed, image_sha, scores, resource):
        if not _sha(image_sha) or not isinstance(scores, dict) or not isinstance(resource, dict):
            raise ValueError("image hash, scores and resource record required")
        score_copy, resource_copy = canonical(scores), canonical(resource)
        if set(scores) != {"vit_class", "clip_score"} or type(scores["vit_class"]) is not int or not 0 <= scores["vit_class"] < 1000 or not isinstance(scores["clip_score"], (int, float)) or not math.isfinite(scores["clip_score"]) or not 0 <= scores["clip_score"] <= 100:
            raise ValueError("invalid independent scorer result")
        key = (self.run_id, state, version, category, context_id, seed)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT resource FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=? AND status='started'", key).fetchone()
            if prior is None:
                raise ValueError("missing or already completed attempt")
            self._validate_resource(resource, json.loads(prior[0]))
            registered = self.db.execute("SELECT image_sha FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()[0]
            if registered is not None and registered != image_sha:
                raise ValueError("image differs from the registered persisted image")
            self.db.execute("UPDATE attempts SET status='complete',image_sha=?,scores=?,resource=? WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", (image_sha, score_copy, resource_copy, *key))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def mark_image_persisted(self, state, version, category, context_id, seed, image_sha):
        if not _sha(image_sha):
            raise ValueError("persisted image SHA is required")
        key = (self.run_id, state, version, category, context_id, seed)
        result = self.db.execute("UPDATE attempts SET image_sha=? WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=? AND status='started' AND image_sha IS NULL", (image_sha, *key))
        if result.rowcount != 1:
            raise ValueError("attempt cannot register another image")

    @staticmethod
    def _validate_resource(resource, previous):
        if any(type(v) is not int or v < 0 for v in resource.values()) or any(k not in resource or resource[k] < v for k, v in previous.items()):
            raise ValueError("resource counters must be nonnegative and monotone")

    def checkpoint_resource(self, state, version, category, context_id, seed, resource):
        key = (self.run_id, state, version, category, context_id, seed)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT resource FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=? AND status='started'", key).fetchone()
            if row is None:
                raise ValueError("missing or already completed attempt")
            self._validate_resource(resource, json.loads(row[0]))
            self.db.execute("UPDATE attempts SET resource=? WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", (canonical(resource), *key))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise


def paired_cluster_bootstrap(values_a, values_b, seed, n=10000, confidence=.95):
    """Input maps context IDs to identical explicit seed-to-value mappings."""
    if set(values_a) != set(values_b) or not values_a or n < 1 or not 0 < confidence < 1:
        raise ValueError("paired context sets and valid bootstrap required")
    ids = sorted(values_a)
    pairs, expected_seeds = [], None
    for key in ids:
        a, b = values_a[key], values_b[key]
        if not isinstance(a, dict) or not isinstance(b, dict) or len(a) != 2 or set(a) != set(b):
            raise ValueError("two explicit paired seeds are required per context")
        if expected_seeds is None:
            expected_seeds = set(a)
        if set(a) != expected_seeds or any(type(s) is not int for s in a) or any(not math.isfinite(x) for x in (*a.values(), *b.values())):
            raise ValueError("the same two finite paired seeds are required for all contexts")
        pairs.append(sum(a[s] - b[s] for s in sorted(a)) / 2)
    rng = random.Random(seed)
    draws = sorted(sum(pairs[rng.randrange(len(pairs))] for _ in pairs) / len(pairs) for _ in range(n))
    tail = (1 - confidence) / 2
    # Nearest-rank, fixed before drawing and independent of observed results.
    return {"difference": sum(pairs) / len(pairs), "lower": draws[max(0, math.ceil(tail*n)-1)],
            "upper": draws[min(n-1, math.ceil((1-tail)*n)-1)], "contexts": len(ids), "draws": n}
