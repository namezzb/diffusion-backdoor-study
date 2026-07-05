#!/bin/bash
# Fix bibaddiff main.py from backup with all PL 2.x patches
cd /opt/data/private/BackdoorDM/attack/t2i_gen/bibaddiff

# Restore from backup
cp main.py.bak main.py

# 1. Replace TestTubeLogger with CSVLogger
sed -i 's/pl.loggers.TestTubeLogger/pl.loggers.CSVLogger/g' main.py
sed -i 's/pytorch_lightning.loggers.TestTubeLogger/pytorch_lightning.loggers.CSVLogger/g' main.py

# 2. Replace DDPPlugin with DDPStrategy
sed -i 's|from pytorch_lightning.plugins import DDPPlugin|from pytorch_lightning.strategies import DDPStrategy|g' main.py
sed -i 's|trainer_kwargs\["plugins"\].append(DDPPlugin(find_unused_parameters=False))|trainer_kwargs["strategy"] = DDPStrategy(find_unused_parameters=False)|g' main.py

# 3. Remove Trainer.add_argparse_args calls
sed -i 's|    parser = Trainer.add_argparse_args(parser)|    # PL 2.x: add_argparse_args removed|g' main.py

# 4. Replace Trainer.from_argparse_args
sed -i 's|trainer = Trainer.from_argparse_args(trainer_opt, \*\*trainer_kwargs)|trainer = Trainer(**trainer_kwargs)|g' main.py

# 5. Fix nondefault_trainer_args
sed -i '/def nondefault_trainer_args/,/return sorted/{
  s/    parser = argparse.ArgumentParser()/# PL 2.x stub/
  s/    parser = Trainer.add_argparse_args(parser)/# removed/
  s/    args = parser.parse_args(\[\])/# removed/
  s/    return sorted(k for k in vars(args) if getattr(opt, k) != getattr(args, k))/    return []/
}' main.py

# 6. Add --gpus argument after --finetune_from
sed -i '/--finetune_from/,/help="path to checkpoint to load model weights from"/{
  /help="path to checkpoint to load model weights from"/a\
    parser.add_argument(\
        "--gpus",\
        type=str,\
        default=None,\
        help="comma-separated GPU ids",\
    )
}' main.py

# 7. Fix accelerator/strategy for PL 2.x
sed -i 's|trainer_config\["accelerator"\] = "ddp"|# PL 2.x: set in gpus block below|g' main.py

# 8. Add weights_only=False to all torch.load calls
sed -i 's/torch.load(opt.finetune_from, map_location="cpu")/torch.load(opt.finetune_from, map_location="cpu", weights_only=False)/g' main.py
find ldm/ -name '*.py' -exec sed -i 's/torch.load(path, map_location="cpu")/torch.load(path, map_location="cpu", weights_only=False)/g' {} \;

# 9. Add del+gc after checkpoint loading
sed -i '/m, u = model.load_state_dict(old_state, strict=False)/a\            del old_state\n            import gc\n            gc.collect()\n            torch.cuda.empty_cache()' main.py

# 10. Use 8-bit AdamW in ddpm.py
sed -i 's|opt = torch.optim.AdamW(params, lr=lr)|import bitsandbytes as bnb\n        opt = bnb.optim.AdamW8bit(params, lr=lr)|g' ldm/models/diffusion/ddpm.py

echo "ALL_PATCHES_APPLIED"
