#!/usr/bin/env python3
with open('/opt/data/private/BackdoorDM/attack/t2i_gen/bibaddiff/main.py', 'r') as f:
    content = f.read()

old_block = '''        if not "gpus" in trainer_config:
            cpu = True
            cpu = True
        else:
            gpuinfo = trainer_config["gpus"]
            print(f"Running on GPUs {gpuinfo}")
            cpu = False
        trainer_opt = argparse.Namespace(**trainer_config)'''

new_block = '''        if not "gpus" in trainer_config:
            cpu = True
        else:
            gpuinfo = trainer_config["gpus"]
            print(f"Running on GPUs {gpuinfo}")
            cpu = False
            gpus_list = [g.strip() for g in gpuinfo.split(",") if g.strip()]
            trainer_config["devices"] = gpus_list
            trainer_config["accelerator"] = "gpu"
            trainer_config["strategy"] = "auto"
            del trainer_config["gpus"]
        trainer_opt = argparse.Namespace(**trainer_config)'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open('/opt/data/private/BackdoorDM/attack/t2i_gen/bibaddiff/main.py', 'w') as f:
        f.write(content)
    print('FIXED')
else:
    print('NOT_FOUND')
    import re
    match = re.search(r'if not "gpus".*?trainer_opt = argparse', content, re.DOTALL)
    if match:
        print(repr(match.group()))
