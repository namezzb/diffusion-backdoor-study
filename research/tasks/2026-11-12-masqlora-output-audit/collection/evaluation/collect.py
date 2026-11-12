"""Generate only normal SD1.5 controls and append scored rows to the run."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


def collect(args):
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
    args.root.mkdir(parents=True, exist_ok=True)
    args.root.joinpath("worker.md").write_text(f"# GPU worker\n\n- PID {os.getpid()}\n- UUID {args.uuid}\n")
    print("Loading CUDA and clean SD1.5", flush=True)

    import torch
    from diffusers import StableDiffusionPipeline
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForImageClassification, CLIPModel, CLIPProcessor

    spec = json.loads((args.root / "controls.json").read_text())
    models = args.assets / "models"
    torch.set_num_threads(4)
    if torch.cuda.device_count() != 1 or os.environ["CUDA_VISIBLE_DEVICES"] != args.uuid:
        raise RuntimeError("Expected one CUDA device bound by UUID")
    torch.empty(1, device="cuda")
    pipe = StableDiffusionPipeline.from_pretrained(
        models / "sd15", torch_dtype=torch.float16, local_files_only=True,
        safety_checker=None, requires_safety_checker=False,
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    clip = CLIPModel.from_pretrained(models / "clip", local_files_only=True).to("cuda").eval()
    clip_processor = CLIPProcessor.from_pretrained(models / "clip", local_files_only=True)
    vit = AutoModelForImageClassification.from_pretrained(
        models / "vit", local_files_only=True,
    ).to("cuda").eval()
    vit_processor = AutoImageProcessor.from_pretrained(models / "vit", local_files_only=True)
    check()

    nouns = ["cat", "car", "dog", "airplane", "truck", "bus", "rabbit", "bird", "person", "landscape"]
    noun_texts = ["a photo of a " + noun for noun in nouns]
    prompts = list(dict.fromkeys(
        prompt for group in spec["strata"].values() for prompt in group["prompts"]
    ))
    texts = list(dict.fromkeys(noun_texts + prompts))

    def features(output, attr):
        if isinstance(output, torch.Tensor):
            return output
        return getattr(output, attr)

    with torch.inference_mode():
        text = features(clip.get_text_features(**clip_processor(
            text=texts, padding=True, return_tensors="pt",
        ).to("cuda")), "pooler_output")
        text = torch.nn.functional.normalize(text, dim=-1)

    log = args.root / "scores.md"
    if not log.exists():
        log.write_text("# Frozen clean-control image scores\n")
    existing = {json.loads(line[2:])["id"] for line in log.read_text().splitlines() if line.startswith("- {")}
    rows = []
    per_split = spec["per_split"]
    for g, (stratum, group) in enumerate(spec["strata"].items()):
        for s, split in enumerate(("calibration", "holdout")):
            variants = group["prompts"]
            if len(variants) > 1:
                variants = variants[2*s:2*s+2]
            for i in range(per_split):
                rows.append({
                    "id": f"{stratum}-{split}-{i:02d}", "stratum": stratum, "split": split,
                    "noun": group["noun"], "prompt": variants[i % len(variants)],
                    "seed": spec["seed_start"] + (2*g+s)*per_split + i,
                    "companion": group.get("companion"),
                })

    images_dir = args.root / "images"
    images_dir.mkdir(exist_ok=True)
    remaining = [row for row in rows if row["id"] not in existing]
    batch_size = spec["batch"]
    for start in range(0, len(remaining), batch_size):
        check()
        batch = remaining[start:start+batch_size]
        paths = [images_dir / (row["id"] + ".png") for row in batch]
        missing = [i for i, path in enumerate(paths) if not path.is_file()]
        with torch.inference_mode():
            if missing:
                out = pipe(
                    [batch[i]["prompt"] for i in missing],
                    generator=[torch.Generator("cuda").manual_seed(batch[i]["seed"]) for i in missing],
                    height=spec["size"], width=spec["size"], num_inference_steps=spec["steps"],
                    guidance_scale=spec["guidance"], callback_on_step_end=callback,
                )
                for i, image in zip(missing, out.images, strict=True):
                    temp = paths[i].with_suffix(".tmp.png")
                    image.save(temp)
                    temp.replace(paths[i])
            images = []
            for path in paths:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            image_features = features(clip.get_image_features(**clip_processor(
                images=images, return_tensors="pt",
            ).to("cuda")), "pooler_output")
            sims = (torch.nn.functional.normalize(image_features, dim=-1) @ text.T).cpu().tolist()
            classes = vit(**vit_processor(images=images, return_tensors="pt").to("cuda")).logits.argmax(dim=-1).cpu().tolist()
        with log.open("a") as f:
            for row, sim, cls in zip(batch, sims, classes, strict=True):
                row.update(
                    source_cosine=sim[texts.index("a photo of a " + row["noun"])],
                    cat_cosine=sim[texts.index(noun_texts[0])],
                    car_cosine=sim[texts.index(noun_texts[1])],
                    dog_cosine=sim[texts.index(noun_texts[2])],
                    prompt_cosine=sim[texts.index(row["prompt"])],
                    vit_top1=vit.config.id2label[cls],
                    clip_top1=nouns[max(range(len(nouns)), key=lambda i: sim[texts.index(noun_texts[i])])],
                )
                f.write("- " + json.dumps(row, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if start % (4 * batch_size) == 0 or start + batch_size >= len(remaining):
            print(f"Clean controls scored {len(existing) + min(start + batch_size, len(remaining))}/{len(rows)}", flush=True)

    print("AUTORESEARCH_METRICS " + json.dumps({"controls": len(rows)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("uuid")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    collect(parser.parse_args())
