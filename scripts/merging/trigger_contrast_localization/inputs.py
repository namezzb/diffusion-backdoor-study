"""Strict structural checks for proposed TCL inputs; no input is generated here."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import unicodedata

PARTITIONS = {"localize": 8, "source": 16, "merge": 16}
KINDS = ("trigger", "dog", "cat", "other")


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def semantic_context_hash(contexts):
    # Token IDs are checked independently below. Adding them after semantic
    # review must not invalidate a review of otherwise identical prompt data.
    without_tokens = [{key: value for key, value in row.items() if key != "tokenization"} for row in contexts]
    content = json.dumps(without_tokens, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256_bytes(content)


def _normal(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _template_fingerprint(text):
    # A mechanical warning, not a substitute for semantic diversity review.
    return " ".join(re.findall(r"[\w]+", _normal(text)))


def validate_structure(contexts):
    if len(contexts) != 320:
        raise ValueError("exactly 320 contexts are required")
    counts, ids, fingerprints = Counter(), set(), set()
    seen = {kind: set() for kind in KINDS}
    all_strata = set()
    for row in contexts:
        stage, stratum, ident, template = (row.get(k) for k in ("partition", "stratum", "id", "template"))
        if stage not in PARTITIONS or not all(isinstance(v, str) and v for v in (stratum, ident, template)):
            raise ValueError("invalid partition, stratum, context id or template")
        if ident in ids or template.count("{subject}") != 1 or template.count("{") != 1 or template.count("}") != 1:
            raise ValueError("duplicate ID or invalid subject template")
        ids.add(ident)
        all_strata.add(stratum)
        counts[stage, stratum] += 1
        fingerprint = _template_fingerprint(template.replace("{subject}", "subject"))
        if fingerprint in fingerprints:
            raise ValueError("exact or punctuation/whitespace template duplicate")
        fingerprints.add(fingerprint)
        other = row.get("other_subject")
        labels = row.get("class_ids")
        if not isinstance(other, str) or not other.strip() or _normal(other) in {"dog", "cat"}:
            raise ValueError("other object must be explicit and distinct")
        if not isinstance(labels, dict) or set(labels) != set(KINDS):
            raise ValueError("frozen labels required for every class")
        for kind in KINDS:
            values = labels[kind]
            if not isinstance(values, list) or not values or len(set(values)) != len(values) or any(type(x) is not int or not 0 <= x < 1000 for x in values):
                raise ValueError("invalid frozen ImageNet class IDs")
        if labels["trigger"] != list(range(281, 288)):
            raise ValueError("trigger target must use fixed cat classes 281 through 287")
        texts = {"dog": template.format(subject="dog"), "cat": template.format(subject="cat"),
                 "other": template.format(subject=other)}
        texts["trigger"] = texts["dog"].replace("o", "ȏ")
        if "o" not in texts["dog"] or row.get("texts") != texts:
            raise ValueError("prompt pairing or exact U+006F to U+020F substitution mismatch")
        for kind in KINDS:
            text = texts[kind]
            normalized = _normal(text)
            if normalized in seen[kind]:
                raise ValueError("duplicate prompt within or across partitions")
            seen[kind].add(normalized)
    if len(all_strata) != 8 or any(counts[stage, stratum] != n for stage, n in PARTITIONS.items() for stratum in all_strata):
        raise ValueError("partition/stratum sizes differ from 8/16/16")
    return {"contexts": len(contexts), "strata": sorted(all_strata), "tokenizer_verified": False,
            "semantic_near_duplicates": "requires documented manual review"}


def validate_contexts(contexts, tokenizer, review_file, review_sha256):
    """Strict gate; a structural pass alone cannot authorize model use."""
    result = validate_structure(contexts)
    if not callable(tokenizer):
        raise ValueError("the pinned tokenizer is required")
    if not isinstance(review_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", review_sha256):
        raise ValueError("independent semantic and near-duplicate review evidence is required")
    with open(review_file, "rb") as stream:
        review_bytes = stream.read()
    if sha256_bytes(review_bytes) != review_sha256:
        raise ValueError("diversity review file hash mismatch")
    diversity_review = json.loads(review_bytes)
    if (not isinstance(diversity_review, dict) or diversity_review.get("passed") is not True
            or diversity_review.get("contexts_sha256") != semantic_context_hash(contexts)
            or not isinstance(diversity_review.get("reviewer"), str) or not diversity_review["reviewer"].strip()
            or not isinstance(diversity_review.get("method"), str) or not diversity_review["method"].strip()):
        raise ValueError("review must name reviewer and method and bind this exact context set")
    for row in contexts:
        for kind in KINDS:
            text = row["texts"][kind]
            unpadded = tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"]
            if not 1 <= len(unpadded) <= 77:
                raise ValueError("untruncated prompt exceeds fixed token length")
            actual = tokenizer(text, padding="max_length", max_length=77, truncation=False, add_special_tokens=True)
            saved = row.get("tokenization", {}).get(kind)
            if saved != {"input_ids": actual["input_ids"], "attention_mask": actual["attention_mask"]} or len(actual["input_ids"]) != 77 or len(actual["attention_mask"]) != 77:
                raise ValueError("stored tokens differ from pinned tokenizer")
    result["tokenizer_verified"] = True
    result["semantic_near_duplicates"] = review_sha256
    return result


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
