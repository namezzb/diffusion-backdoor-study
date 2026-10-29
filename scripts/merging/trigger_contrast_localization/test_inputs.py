import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from inputs import semantic_context_hash, validate_contexts, validate_structure


def sample_rows():
    rows = []
    for stage, count in (("localize", 8), ("source", 16), ("merge", 16)):
        for group in range(8):
            for index in range(count):
                template = f"A {{subject}} in distinct fixture {stage} {group} {index}"
                dog = template.format(subject="dog")
                texts = {"dog": dog, "trigger": dog.replace("o", "ȏ"),
                         "cat": template.format(subject="cat"), "other": template.format(subject="horse")}
                rows.append({"id": f"{stage}-{group}-{index}", "partition": stage, "stratum": str(group),
                             "template": template, "other_subject": "horse", "texts": texts,
                             "class_ids": {"trigger": list(range(281, 288)), "dog": [151], "cat": [281], "other": [339]}})
    return rows


class InputsTests(unittest.TestCase):
    def test_partition_and_exact_trigger(self):
        rows = sample_rows()
        result = validate_structure(rows)
        self.assertEqual(result["contexts"], 320)
        self.assertFalse(result["tokenizer_verified"])
        rows[0]["texts"]["trigger"] = rows[0]["texts"]["dog"]
        with self.assertRaisesRegex(ValueError, "substitution"):
            validate_structure(rows)

    def test_cross_partition_duplicate(self):
        rows = sample_rows()
        rows[-1]["template"] = rows[0]["template"]
        with self.assertRaisesRegex(ValueError, "template duplicate"):
            validate_structure(rows)

    def test_counts(self):
        rows = sample_rows()
        rows[0]["stratum"] = rows[1]["stratum"] = "new"
        with self.assertRaisesRegex(ValueError, "stratum sizes"):
            validate_structure(rows)

    def test_frozen_labels_must_not_be_empty(self):
        rows = sample_rows()
        rows[0]["class_ids"]["other"] = []
        with self.assertRaisesRegex(ValueError, "ImageNet"):
            validate_structure(rows)

    def test_real_gate_requires_tokenizer_and_semantic_review(self):
        rows = sample_rows()
        with self.assertRaisesRegex(ValueError, "tokenizer"):
            validate_contexts(rows, None, None, "")
        def fake_tokenizer(text, **kwargs):
            if kwargs.get("padding"):
                return {"input_ids": [1] * 77, "attention_mask": [1] * 77}
            return {"input_ids": [1, 2]}
        with self.assertRaisesRegex(ValueError, "semantic"):
            validate_contexts(rows, fake_tokenizer, None, "")
        for row in rows:
            row["tokenization"] = {kind: fake_tokenizer(text, padding="max_length") for kind, text in row["texts"].items()}
        review = {"passed": True, "reviewer": "fixture reviewer", "method": "test fixture", "contexts_sha256": semantic_context_hash(rows)}
        data = json.dumps(review).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            self.assertTrue(validate_contexts(rows, fake_tokenizer, path, digest)["tokenizer_verified"])
            rows[0]["tokenization"]["dog"]["input_ids"][0] = 2
            with self.assertRaisesRegex(ValueError, "stored tokens"):
                validate_contexts(rows, fake_tokenizer, path, digest)
            rows[0]["texts"]["dog"] = "changed"
            with self.assertRaisesRegex(ValueError, "substitution"):
                validate_contexts(rows, fake_tokenizer, path, digest)


if __name__ == "__main__":
    unittest.main()
