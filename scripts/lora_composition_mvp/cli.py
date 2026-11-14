"""Single unified CLI entrypoint for CCF-A Paper 1 minimal verification (MVP-v1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Support both `python3 -m scripts.lora_composition_mvp.cli` and `python3 scripts/lora_composition_mvp/cli.py`
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lora_composition_mvp.config import (
    CANONICAL_ARMS,
    CANONICAL_SCENARIOS,
    MVPConfig,
    load_config,
    save_config,
)
from scripts.lora_composition_mvp.io_utils import (
    LoRAAdapter,
    RunSignalError,
    check_permission,
    compute_adapter_norms,
    enforce_offline_env,
    event,
    load_lora_adapter,
    md_write,
)


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _resolve_dtype(requested: str, device: str) -> str:
    if requested != "auto":
        return requested
    return "float16" if str(device).startswith("cuda") else "float32"


def _resolve_partner_test(
    cfg: MVPConfig,
    run_path: Path,
    overwrite: bool = False,
) -> tuple[LoRAAdapter, dict[str, Any]]:
    from scripts.lora_composition_mvp.operators import extract_svd_lora_from_model_diff

    if cfg.p_test_mode == "external_lora":
        assert cfg.p_test_lora_path is not None
        adapter = load_lora_adapter(cfg.p_test_lora_path, name="p_test_external")
        norms = compute_adapter_norms(adapter)
        return adapter, {
            "mode": "external_lora",
            "path": cfg.p_test_lora_path,
            "sha256": adapter.metadata.get("sha256"),
            "layer_count": norms["layer_count"],
            "total_frobenius": norms["total_frobenius"],
        }

    out_path = run_path / "artifacts" / f"p_test_svd{cfg.p_test_svd_rank}" / "adapter.safetensors"
    if out_path.is_file() and not overwrite:
        adapter = load_lora_adapter(out_path, name=f"p_test_svd{cfg.p_test_svd_rank}")
        norms = compute_adapter_norms(adapter)
        return adapter, {
            "mode": "svd_diff_cached",
            "path": str(out_path),
            "sha256": adapter.metadata.get("sha256"),
            "layer_count": norms["layer_count"],
            "total_frobenius": norms["total_frobenius"],
        }

    adapter, stats = extract_svd_lora_from_model_diff(
        base_model_dir=cfg.model_dir,
        finetuned_model_dir=cfg.dreamshaper_dir,
        rank=cfg.p_test_svd_rank,
        out_path=out_path,
    )
    return adapter, {"mode": "svd_diff", "path": str(out_path), **stats}


def _resolve_arm_adapter(cfg: MVPConfig, run_path: Path, arm: str) -> LoRAAdapter:
    if arm == "benign":
        return load_lora_adapter(cfg.benign_adapter, name="benign")
    if arm == "masqlora":
        return load_lora_adapter(cfg.masqlora_adapter, name="masqlora")
    ckpt = run_path / "arms" / arm / "adapter.safetensors"
    return load_lora_adapter(ckpt, name=arm)


def cmd_prepare_partner(
    cfg: MVPConfig,
    run_path: Path,
    device: str,
    dtype: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    from scripts.lora_composition_mvp.trainers import (
        build_or_load_p_train_proxy,
        load_sd15_components,
        verify_reused_adapter,
    )

    run_path.mkdir(parents=True, exist_ok=True)
    save_config(cfg, run_path / "config_frozen.json")
    enforce_offline_env()

    p_test_adapter, p_test_stats = _resolve_partner_test(cfg, run_path, overwrite=overwrite)
    benign_audit = verify_reused_adapter("benign", cfg.benign_adapter, cfg.benign_expected_sha256)
    masqlora_audit = verify_reused_adapter("masqlora", cfg.masqlora_adapter, cfg.masqlora_expected_sha256)

    components = load_sd15_components(cfg.model_dir, device=device, dtype_str=dtype)
    p_train_path = run_path / "artifacts" / "p_train_proxy" / "adapter.safetensors"
    p_train_adapter = build_or_load_p_train_proxy(
        cfg=cfg,
        unet=components["unet"],
        tokenizer=components["tokenizer"],
        text_encoder=components["text_encoder"],
        out_path=p_train_path,
        device=device,
    )
    p_train_norms = compute_adapter_norms(p_train_adapter)

    manifest = {
        "run_id": cfg.run_id,
        "p_test_mode": p_test_stats.get("mode"),
        "p_test_path": p_test_stats.get("path"),
        "p_test_sha256": p_test_stats.get("sha256"),
        "p_test_style_suffix": cfg.p_test_style_suffix,
        "p_train_path": cfg.p_train_lora_path or str(p_train_path),
        "p_train_frobenius": f"{p_train_norms['total_frobenius']:.4f}",
        "benign_sha256": benign_audit["sha256"],
        "benign_frobenius": f"{benign_audit['total_frobenius']:.4f}",
        "masqlora_sha256": masqlora_audit["sha256"],
        "masqlora_frobenius": f"{masqlora_audit['total_frobenius']:.4f}",
        "lpips_weights_path": str(cfg.lpips_weights_path),
    }
    md_write(run_path / "artifacts" / "partner_manifest.md", "MVP-v1 Partner & Baseline Manifest", manifest)
    event(run_path, "prepare_partner_done", p_test_mode=p_test_stats.get("mode"), p_test_sha=p_test_stats.get("sha256"))
    return {
        "p_test": p_test_stats,
        "p_train_norms": p_train_norms,
        "benign": benign_audit,
        "masqlora": masqlora_audit,
        "components": components,
        "p_train_adapter": p_train_adapter,
        "p_test_adapter": p_test_adapter,
    }


def cmd_train(
    cfg: MVPConfig,
    run_path: Path,
    arms: list[str],
    device: str,
    dtype: str,
    state_dir: Path | None,
    gpu_uuid: str | None,
    components: dict[str, Any] | None = None,
    p_train_adapter: LoRAAdapter | None = None,
) -> dict[str, Any]:
    from scripts.lora_composition_mvp.trainers import (
        build_or_load_p_train_proxy,
        encode_image_latents,
        load_sd15_components,
        train_ours_mvp,
        train_poisonlora,
        verify_reused_adapter,
    )

    enforce_offline_env()
    save_config(cfg, run_path / "config_frozen.json")
    if components is None:
        components = load_sd15_components(cfg.model_dir, device=device, dtype_str=dtype)
    if p_train_adapter is None:
        p_train_adapter = build_or_load_p_train_proxy(
            cfg=cfg,
            unet=components["unet"],
            tokenizer=components["tokenizer"],
            text_encoder=components["text_encoder"],
            out_path=run_path / "artifacts" / "p_train_proxy" / "adapter.safetensors",
            device=device,
        )

    need_vae_latents = "poisonlora" in arms or ("ours_mvp" in arms and cfg.ours_version == "v2_distill")
    cat_latents = None
    car_latents = None
    if need_vae_latents:
        cat_dir, car_dir = cfg.resolve_data_dirs()
        cat_latents = encode_image_latents(components["vae"], cat_dir, cfg.resolution, device=device)
        car_latents = encode_image_latents(components["vae"], car_dir, cfg.resolution, device=device)

    results: dict[str, Any] = {}
    for arm in arms:
        check_permission(run_path, state_dir=state_dir, gpu_uuid=gpu_uuid)
        if arm == "benign":
            results[arm] = verify_reused_adapter("benign", cfg.benign_adapter, cfg.benign_expected_sha256)
        elif arm == "masqlora":
            results[arm] = verify_reused_adapter("masqlora", cfg.masqlora_adapter, cfg.masqlora_expected_sha256)
        elif arm == "poisonlora":
            results[arm] = train_poisonlora(
                cfg=cfg,
                run_dir=run_path,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
                state_dir=state_dir,
                gpu_uuid=gpu_uuid,
            )
        elif arm == "ours_mvp":
            results[arm] = train_ours_mvp(
                cfg=cfg,
                run_dir=run_path,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
                p_train_adapter=p_train_adapter,
                state_dir=state_dir,
                gpu_uuid=gpu_uuid,
            )
        else:
            raise ValueError(f"Unknown arm: {arm!r}")
    return results


def cmd_compose(
    cfg: MVPConfig,
    run_path: Path,
    arms: list[str],
    scenarios: list[str],
    device: str,
    dtype: str,
    state_dir: Path | None,
    gpu_uuid: str | None,
    overwrite: bool = False,
    components: dict[str, Any] | None = None,
    p_test_adapter: LoRAAdapter | None = None,
) -> dict[tuple[str, str], Any]:
    from scripts.lora_composition_mvp.operators import (
        ComposedLoRAPlan,
        compose_s0_single,
        compose_s1_partial_te0,
        compose_s2_ties,
        optimize_s3_ziplora,
        prepare_s2_klora,
    )
    from scripts.lora_composition_mvp.trainers import _encode_prompt, encode_image_latents, load_sd15_components

    enforce_offline_env()
    if p_test_adapter is None and any(s != "S0" for s in scenarios):
        p_test_adapter, _ = _resolve_partner_test(cfg, run_path, overwrite=False)

    need_s3 = "S3_ziplora" in scenarios
    s3_car_latents = None
    s3_subj_emb = None
    s3_sty_emb = None
    if need_s3:
        if components is None:
            components = load_sd15_components(cfg.model_dir, device=device, dtype_str=dtype)
        # Check if all S3 plans are already cached cleanly on disk
        all_s3_cached = (not overwrite) and all(
            (run_path / "composed" / arm / "S3_ziplora" / "adapter.safetensors").is_file()
            and (run_path / "composed" / arm / "S3_ziplora" / "plan_meta.json").is_file()
            for arm in arms
        )
        if not all_s3_cached:
            _, car_dir = cfg.resolve_data_dirs()
            s3_car_latents = encode_image_latents(components["vae"], car_dir, cfg.resolution, device=device)
            s3_subj_emb = _encode_prompt(
                components["tokenizer"], components["text_encoder"], cfg.clean_prompt, device=device
            ).repeat(s3_car_latents.shape[0], 1, 1)
            style_prompt = f"a car, {cfg.p_test_style_suffix}"
            s3_sty_emb = _encode_prompt(
                components["tokenizer"], components["text_encoder"], style_prompt, device=device
            ).repeat(s3_car_latents.shape[0], 1, 1)

    plans: dict[tuple[str, str], ComposedLoRAPlan] = {}
    for arm in arms:
        cand = _resolve_arm_adapter(cfg, run_path, arm)
        for scen in scenarios:
            check_permission(run_path, state_dir=state_dir, gpu_uuid=gpu_uuid)
            scen_dir = run_path / "composed" / arm / scen
            scen_dir.mkdir(parents=True, exist_ok=True)
            if scen == "S0":
                plan = compose_s0_single(cand)
            elif scen == "S1":
                assert p_test_adapter is not None
                plan = compose_s1_partial_te0(
                    cand,
                    p_test_adapter,
                    cand_te_scale=cfg.s1_cand_te_scale,
                    cand_unet_scale=cfg.s1_cand_unet_scale,
                    partner_scale=cfg.s1_partner_scale,
                )
            elif scen == "S2_ties":
                assert p_test_adapter is not None
                plan = compose_s2_ties(
                    cand,
                    p_test_adapter,
                    cand_scale=cfg.s2_cand_scale,
                    partner_scale=cfg.s2_partner_scale,
                    density=cfg.s2_ties_density,
                    lambda_scale=cfg.s2_ties_lambda,
                )
            elif scen == "S2_klora":
                assert p_test_adapter is not None
                plan = prepare_s2_klora(
                    cand,
                    p_test_adapter,
                    cand_scale=cfg.s2_cand_scale,
                    partner_scale=cfg.s2_partner_scale,
                    k_rank_ref=cfg.s2_klora_k_rank_ref,
                    alpha=cfg.s2_klora_alpha,
                    beta=cfg.s2_klora_beta,
                )
            elif scen == "S3_ziplora":
                cached_adapter = scen_dir / "adapter.safetensors"
                cached_meta = scen_dir / "plan_meta.json"
                if cached_adapter.is_file() and cached_meta.is_file() and not overwrite:
                    meta = json.loads(cached_meta.read_text(encoding="utf-8"))
                    merged = load_lora_adapter(cached_adapter, name=f"{arm}_S3_ziplora")
                    plan = ComposedLoRAPlan(
                        arm=arm,
                        scenario="S3_ziplora",
                        mode="static_delta",
                        static_adapter=merged,
                        effective_cand_norms=meta["effective_cand_norms"],
                        effective_merged_norms=meta["effective_merged_norms"],
                        diagnostics=meta["diagnostics"],
                    )
                else:
                    assert components is not None and p_test_adapter is not None
                    plan = optimize_s3_ziplora(
                        cand=cand,
                        partner=p_test_adapter,
                        unet=components["unet"],
                        subject_latents=s3_car_latents,
                        subject_text_emb=s3_subj_emb,
                        style_latents=s3_car_latents,
                        style_text_emb=s3_sty_emb,
                        num_train_timesteps=int(getattr(components["scheduler"].config, "num_train_timesteps", 1000)),
                        steps=cfg.s3_ziplora_steps,
                        lr=cfg.s3_ziplora_lr,
                        lambda_cos=cfg.s3_ziplora_lambda_cos,
                        cand_init_scale=cfg.s3_cand_init_scale,
                        partner_init_scale=cfg.s3_partner_init_scale,
                        seed=cfg.seed,
                        out_adapter_path=cached_adapter,
                    )
                    cached_meta.write_text(
                        json.dumps(
                            {
                                "effective_cand_norms": plan.effective_cand_norms,
                                "effective_merged_norms": plan.effective_merged_norms,
                                "diagnostics": plan.diagnostics,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
            else:
                raise ValueError(f"Unknown scenario: {scen!r}")

            plans[(arm, scen)] = plan
            md_write(
                scen_dir / "composition.md",
                f"Composed Plan {arm} x {scen}",
                {
                    "arm": arm,
                    "scenario": scen,
                    "mode": plan.mode,
                    "cand_total_frobenius": f"{plan.effective_cand_norms.get('total_frobenius', 0.0):.6f}",
                    "merged_total_frobenius": f"{plan.effective_merged_norms.get('total_frobenius', 0.0):.6f}",
                    "diagnostics": json.dumps(plan.diagnostics),
                },
            )
    return plans


def cmd_evaluate(
    cfg: MVPConfig,
    run_path: Path,
    arms: list[str],
    scenarios: list[str],
    device: str,
    dtype: str,
    state_dir: Path | None,
    gpu_uuid: str | None,
    skip_grids: bool = False,
    overwrite: bool = False,
    components: dict[str, Any] | None = None,
    plans: dict[tuple[str, str], Any] | None = None,
) -> Path:
    from scripts.lora_composition_mvp.evaluate import (
        OfflineScorer,
        aggregate_metrics,
        build_comparison_grids,
        build_eval_schedule,
        evaluate_gates,
        generate_eval_images,
        score_eval_jobs,
        write_evaluation_report,
    )
    from scripts.lora_composition_mvp.trainers import load_sd15_components

    enforce_offline_env()
    if components is None:
        components = load_sd15_components(cfg.model_dir, device=device, dtype_str=dtype)
    if plans is None:
        plans = cmd_compose(
            cfg=cfg,
            run_path=run_path,
            arms=arms,
            scenarios=scenarios,
            device=device,
            dtype=dtype,
            state_dir=state_dir,
            gpu_uuid=gpu_uuid,
            overwrite=False,
            components=components,
        )

    jobs = build_eval_schedule(cfg, arms=arms, scenarios=scenarios, include_neighborhood=True)
    generate_eval_images(
        cfg=cfg,
        run_dir=run_path,
        jobs=jobs,
        plans=plans,
        components=components,
        state_dir=state_dir,
        gpu_uuid=gpu_uuid,
    )

    if str(device).startswith("cuda"):
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    scorer = OfflineScorer(cfg, device=device)
    records = score_eval_jobs(cfg=cfg, run_dir=run_path, jobs=jobs, scorer=scorer, overwrite=overwrite)
    aggregated = aggregate_metrics(records)
    gates = evaluate_gates(cfg, aggregated)
    grids = [] if skip_grids else build_comparison_grids(cfg=cfg, run_dir=run_path, jobs=jobs)
    report_path = write_evaluation_report(
        cfg=cfg,
        run_dir=run_path,
        plans=plans,
        aggregated=aggregated,
        gates=gates,
        grids=grids,
        lpips_status=scorer.lpips_status,
    )
    event(run_path, "evaluate_done", images_scored=len(records), all_gates_passed=gates["all_gates_passed"])
    return report_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Unified CLI for CCF-A Paper 1 MVP-v1 (LoRA Composition Backdoor)."
    )
    p.add_argument(
        "command",
        choices=["prepare-partner", "train", "compose", "evaluate", "run-all"],
        help="Pipeline stage to execute (or run-all).",
    )
    p.add_argument("--config", type=str, default=None, help="Path to MVP JSON config file.")
    p.add_argument("--run-dir", type=str, default=None, help="Run directory (default: results/<run_id>).")
    p.add_argument("--state-dir", type=str, default=None, help="Directory holding permission.md (default: --run-dir).")
    p.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"], help="Execution device.")
    p.add_argument("--dtype", type=str, default="auto", choices=["auto", "float16", "float32"], help="Base model dtype.")
    p.add_argument("--gpu-uuid", type=str, default=None, help="Target GPU UUID for health verification.")
    p.add_argument("--arms", nargs="+", default=list(CANONICAL_ARMS), help="Arms to process.")
    p.add_argument("--scenarios", nargs="+", default=list(CANONICAL_SCENARIOS), help="Scenarios to compose/evaluate.")
    p.add_argument("--max-steps", type=int, default=None, help="Override cfg.max_train_steps.")
    p.add_argument("--max-compute-seconds", type=float, default=None, help="Override compute time limit.")
    p.add_argument("--skip-grids", action="store_true", help="Skip building 4-col visual grids.")
    p.add_argument("--overwrite", action="store_true", help="Recompute cached artifacts/scores.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    overrides: dict[str, Any] = {}
    if args.max_steps is not None:
        overrides["max_train_steps"] = args.max_steps
    if args.max_compute_seconds is not None:
        overrides["max_compute_seconds"] = args.max_compute_seconds

    cfg = load_config(args.config, overrides=overrides)
    run_path = Path(args.run_dir) if args.run_dir else Path("results") / cfg.run_id
    state_dir = Path(args.state_dir) if args.state_dir else run_path
    device = _resolve_device(args.device)
    dtype = _resolve_dtype(args.dtype, device)

    run_path.mkdir(parents=True, exist_ok=True)
    md_write(
        run_path / "RUN_STATE.md",
        "MVP-v1 Run State",
        {
            "run_id": cfg.run_id,
            "command": args.command,
            "status": "in_progress",
            "device": device,
            "dtype": dtype,
        },
    )

    try:
        check_permission(run_path, state_dir=state_dir, gpu_uuid=args.gpu_uuid)
        if args.command == "prepare-partner":
            cmd_prepare_partner(cfg, run_path, device=device, dtype=dtype, overwrite=args.overwrite)
        elif args.command == "train":
            train_arms = [a for a in args.arms if a in {"poisonlora", "ours_mvp", "benign", "masqlora"}]
            cmd_train(
                cfg=cfg,
                run_path=run_path,
                arms=train_arms,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
            )
        elif args.command == "compose":
            cmd_compose(
                cfg=cfg,
                run_path=run_path,
                arms=args.arms,
                scenarios=args.scenarios,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
                overwrite=args.overwrite,
            )
        elif args.command == "evaluate":
            cmd_evaluate(
                cfg=cfg,
                run_path=run_path,
                arms=args.arms,
                scenarios=args.scenarios,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
                skip_grids=args.skip_grids,
                overwrite=args.overwrite,
            )
        elif args.command == "run-all":
            prep = cmd_prepare_partner(cfg, run_path, device=device, dtype=dtype, overwrite=args.overwrite)
            cmd_train(
                cfg=cfg,
                run_path=run_path,
                arms=args.arms,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
                components=prep["components"],
                p_train_adapter=prep["p_train_adapter"],
            )
            plans = cmd_compose(
                cfg=cfg,
                run_path=run_path,
                arms=args.arms,
                scenarios=args.scenarios,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
                overwrite=args.overwrite,
                components=prep["components"],
                p_test_adapter=prep["p_test_adapter"],
            )
            cmd_evaluate(
                cfg=cfg,
                run_path=run_path,
                arms=args.arms,
                scenarios=args.scenarios,
                device=device,
                dtype=dtype,
                state_dir=state_dir,
                gpu_uuid=args.gpu_uuid,
                skip_grids=args.skip_grids,
                overwrite=args.overwrite,
                components=prep["components"],
                plans=plans,
            )

        md_write(
            run_path / "RUN_STATE.md",
            "MVP-v1 Run State",
            {"run_id": cfg.run_id, "command": args.command, "status": "done"},
        )
        return 0
    except RunSignalError as exc:
        md_write(
            run_path / "RUN_STATE.md",
            "MVP-v1 Run State",
            {
                "run_id": cfg.run_id,
                "command": args.command,
                "status": f"signal_{exc.exit_code}",
                "message": str(exc),
            },
        )
        event(run_path, "run_signal", exit_code=exc.exit_code, message=str(exc))
        print(f"[signal:{exc.exit_code}] {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
