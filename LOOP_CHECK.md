# BackdoorDM Loop Check

> ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## Loop Prompt

```
BackdoorDM loop:
1. ssh amax -p 25579 "bash /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh"
2. benchmark=STOPPED & eval_queue=STOPPED → restart: cd $BD && nohup bash scripts/run_benchmark.sh > logs/benchmark/nohup.log 2>&1 &
3. log stale >30min → check nvidia-smi, if 0% util kill main_eval.py, restart benchmark
4. eval_proc_count >1 → kill larger PID (rogue), keep smaller
5. phase=COMPLETE → collect results, update report, notify user
6. Append to work_log.md: results count, phase, actions taken
```

## Restart Command

```bash
ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && nohup bash scripts/run_benchmark.sh > logs/benchmark/nohup.log 2>&1 &"
```

## Key Files
- Healthcheck: server `scripts/loop_healthcheck.sh`
- Benchmark: server `scripts/run_benchmark.sh`
- Log: server `logs/benchmark/benchmark.log`
- Markers: server `logs/benchmark/done/`
- Report: local `reports/03-reproduction-results/backdoordm_final_report.md`
