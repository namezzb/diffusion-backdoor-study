"""Generate and score paired benign SD1.5 outputs for semantic-integrity auditing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


def collect(root, assets, uuid):
    last_refresh = [time.monotonic()]
    stopped = threading.Event()

    def listen():
        for line in sys.stdin:
            if line.strip() == "continue":
                last_refresh[0] = time.monotonic()
        stopped.set()

    def check():
        if stopped.is_set() or time.monotonic() - last_refresh[0] > 70:
            raise RuntimeError("Resource observation ended or expired")

    def callback(_pipe, _step, _time, kwargs):
        check()
        return kwargs

    threading.Thread(target=listen, daemon=True).start()
    (root / "worker.md").write_text(f"# GPU worker\n\n- PID {os.getpid()}\n- UUID {uuid}\n")
    spec = json.loads((root / "controls.json").read_text())
    adapter = root / "benign.safetensors"
    if not adapter.is_file():
        adapter = assets / "results/masqlora-20261105-sd15-v1/benign/adapter.safetensors"
    if hashlib.sha256(adapter.read_bytes()).hexdigest() != spec["adapter_sha256"]:
        raise ValueError("Unexpected benign adapter weights")
    print("Loading SD1.5 and the verified benign LoRA", flush=True)
    import torch
    from diffusers import StableDiffusionPipeline
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    torch.set_num_threads(4)
    if os.environ["CUDA_VISIBLE_DEVICES"] != uuid or torch.cuda.device_count() != 1:
        raise RuntimeError("Expected one CUDA device bound by UUID")
    torch.empty(1, device="cuda")
    models = assets / "models"
    pipe = StableDiffusionPipeline.from_pretrained(
        models / "sd15", torch_dtype=torch.float16, local_files_only=True,
        safety_checker=None, requires_safety_checker=False,
    ).to("cuda")
    pipe.load_lora_weights(str(adapter.parent), weight_name=adapter.name,
                           adapter_name="verified_benign", local_files_only=True)
    pipe.set_progress_bar_config(disable=True)
    clip = CLIPModel.from_pretrained(models / "clip", local_files_only=True).to("cuda").eval()
    processor = CLIPProcessor.from_pretrained(models / "clip", local_files_only=True)
    normalize = torch.nn.functional.normalize
    out_dir = root / "images"
    out_dir.mkdir(exist_ok=True)
    ledger = root / "scores.md"
    if not ledger.exists():
        ledger.write_text("# Paired benign generation scores\n")
    existing = {}
    for line in ledger.read_text().splitlines():
        if line.startswith("- {"):
            row = json.loads(line[2:])
            existing[row["id"]] = row

    # Scores of four overlapping crops allow the audit to recover a small object.
    patches = [(0, 0, 320, 320), (192, 0, 512, 320),
               (0, 192, 320, 512), (192, 192, 512, 512)]
    expected = len(spec["scenes"]) * len(spec["scales"]) * 2 * spec["seeds"]
    for scene_no, scene in enumerate(spec["scenes"]):
        check()
        nouns = scene["nouns"]
        prompts = [scene["text"].format(noun=noun) for noun in nouns]
        labels = [f"a photo of a {noun}" for noun in nouns]
        with torch.inference_mode():
            text = normalize(clip.get_text_features(**processor(
                text=labels + prompts, padding=True, return_tensors="pt").to("cuda")), dim=-1)
        for scale_no, scale in enumerate(spec["scales"]):
            pipe.set_adapters("verified_benign", adapter_weights=scale)
            for label, prompt in enumerate(prompts):
                rows = []
                for i in range(spec["seeds"]):
                    row = {
                        "id": f"{scene['id']}-{scale_no}-{label}-{i:02}",
                        "scene": scene["id"], "split": scene["split"],
                        "media": scene["media"], "layout": scene["layout"], "scale": scale,
                        "scale_no": scale_no, "label": label, "index": i,
                        "seed": spec["seed_start"] + scene_no * spec["seeds"] + i,
                    }
                    if row["id"] not in existing:
                        rows.append(row)
                if not rows:
                    continue
                check()
                paths = [out_dir / (row["id"] + ".png") for row in rows]
                missing = [i for i, path in enumerate(paths) if not path.is_file()]
                with torch.inference_mode():
                    if missing:
                        generated = pipe(
                            [prompt] * len(missing),
                            generator=[torch.Generator("cuda").manual_seed(rows[i]["seed"]) for i in missing],
                            height=spec["size"], width=spec["size"],
                            num_inference_steps=spec["steps"], guidance_scale=spec["guidance"],
                            callback_on_step_end=callback,
                        ).images
                        for i, image in zip(missing, generated, strict=True):
                            temp = paths[i].with_suffix(".tmp.png")
                            image.save(temp)
                            temp.replace(paths[i])
                    images = []
                    for path in paths:
                        with Image.open(path) as image:
                            images.append(image.convert("RGB"))
                    embeddings = []
                    scores = []
                    for patch in [None, *patches]:
                        check()
                        views = [image.crop(patch) for image in images] if patch else images
                        feature = normalize(clip.get_image_features(**processor(
                            images=views, return_tensors="pt").to("cuda")), dim=-1)
                        scores.append((feature @ text.T).cpu().tolist())
                        if patch is None:
                            embeddings = feature.cpu()
                    for i, row in enumerate(rows):
                        base_id = f"{scene['id']}-0-{label}-{row['index']:02}"
                        if scale_no == 0:
                            row["base_cosine"] = 1.0
                        else:
                            with Image.open(out_dir / (base_id + ".png")) as image:
                                feat = normalize(clip.get_image_features(**processor(
                                    images=[image.convert("RGB")], return_tensors="pt").to("cuda")), dim=-1)
                            row["base_cosine"] = float(feat.cpu()[0] @ embeddings[i])
                        row["full"] = scores[0][i]
                        row["crops"] = [score[i][:2] for score in scores[1:]]
                with ledger.open("a") as output:
                    for row in rows:
                        output.write("- " + json.dumps(row, allow_nan=False) + "\n")
                        existing[row["id"]] = row
                    output.flush()
                    os.fsync(output.fileno())
                print(f"Scored {len(existing)}/{expected} clean images", flush=True)
    if len(existing) != expected:
        raise ValueError("Unexpected collection size")
    print("AUTORESEARCH_METRICS " + json.dumps({"images": expected}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("uuid")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    collect(**vars(parser.parse_args()))
