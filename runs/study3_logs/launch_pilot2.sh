#!/bin/sh
# Study 3 second pilot (prereg/ADDENDUM_4_study3.md), after the fixes from the first pilot's hand reading:
# seeds 102-103, all five arms, three subject models (30 games), into runs/pilot_s3b. Excluded from all results.
# Gemma is served by DeepInfra's full-precision endpoint where possible (NextBit's 4-bit one garbled ~6% of notes).
# Usage: launch_pilot2.sh [OUT_DIR] [extra flags, e.g. --mock]; running it again resumes (--skip-done).
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
OUT=${1:-runs/pilot_s3b}; [ $# -gt 0 ] && shift  # (a bare "shift" with no arguments exits dash)
LOG=$OUT/logs; mkdir -p $LOG
COMMON="--arms P0,PF,PE,PT,PC --seeds 102-103 --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --max-tokens 512 --prefer-provider google/gemma-3-12b-it=deepinfra --skip-done --out $OUT $*"
run() { # model slug cap
  python -m sting.run --subject-model $1 --cap-usd $3 --workers 5 $COMMON >> $LOG/$2.log 2>&1 &  # append: a relaunch keeps the earlier output
}
run mistralai/ministral-14b-2512 m14 0.80
run qwen/qwen3.5-9b              q9  0.60
run mistralai/ministral-8b-2512  m8  0.60
wait
