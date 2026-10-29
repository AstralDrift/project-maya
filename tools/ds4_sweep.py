#!/usr/bin/env python3
"""One-change-at-a-time --bench sweep for a DeepSeek config on this PC (RTX 4090 24 GB, 32 GB RAM).

  tools/ds4_sweep.py BASE.json LABEL [KEY=VALUE ...] [--arg FLAG VALUE ...] [--repeat N]

KEY=VALUE goes into the variant config's "env"; --arg sets (or adds) an engine flag in "args" (VALUE "-" drops it).
Each run: `maya.sh --bench --config <variant>` inside a memory-capped systemd scope (systemd-oomd ends whole scopes,
so a spike takes the engine, not the terminal), core dumps off. Results append to bench-sweep.jsonl next to this
repo's maya-bench.txt, one row per run, with the variant's exact env/args and the bench text.
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    base, label, rest = Path(a[0]).resolve(), a[1], a[2:]
    cfg = json.loads(base.read_text())
    env, args, repeat = dict(cfg.get("env") or {}), list(cfg.get("args") or []), 1
    i = 0
    while i < len(rest):
        r = rest[i]
        if r == "--repeat":
            repeat = int(rest[i + 1]); i += 2; continue
        if r == "--arg":
            flag, val = rest[i + 1], rest[i + 2]; i += 3
            if flag in args:
                j = args.index(flag)
                has_val = j + 1 < len(args) and not args[j + 1].startswith("--")
                del args[j:j + (2 if has_val else 1)]
            if val != "-":
                args += [flag] if val == "" else [flag, val]
            continue
        k, _, v = r.partition("=")
        env[k] = v; i += 1
    cfg["env"], cfg["args"] = env, args
    out = base.with_name(f"sweep-{label}.json")
    out.write_text(json.dumps(cfg, indent=1))
    log = ROOT / "bench-sweep.jsonl"
    for rep in range(repeat):
        t0 = time.time()
        cmd = ["systemd-run", "--user", "--scope", "--quiet", f"--unit=ds4-sweep-{label}-{os.getpid()}-{rep}",
               "-p", f"MemoryMax={os.environ.get('MAYA_MEMMAX', '28G')}", "-p", "MemoryHigh=infinity",
               "bash", "-c", 'ulimit -c 0; exec "$@"', "_", str(ROOT / "maya.sh"), "--plain", "--bench", "--config", str(out)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        txt = (ROOT / "maya-bench.txt").read_text(errors="replace") if (ROOT / "maya-bench.txt").exists() else ""
        if (ROOT / "maya-bench.txt").stat().st_mtime < t0 if txt else True:
            txt = ""                                   # stale file from an earlier run: this one wrote nothing
        nums = {k: float(v) for k, v in re.findall(r"(decode|prefill[^:\n]*?)\D*?([\d.]+) tok", txt)}
        row = {"ts": time.strftime("%F %T"), "label": label, "rep": rep, "rc": p.returncode, "secs": round(time.time() - t0),
               "env": env, "args": args, "parsed": nums, "bench": txt, "tail": (p.stdout + p.stderr)[-1500:]}
        with open(log, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(label, rep, p.returncode, nums or "(no bench output; see bench-sweep.jsonl tail)")


if __name__ == "__main__":
    main()
