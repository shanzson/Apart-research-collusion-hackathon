#!/bin/sh
# Study 3 pilot (prereg/ADDENDUM_4_study3.md): seeds 100-101, all five arms, three subject models (30 games).
# Excluded from all results. Usage: launch_pilot.sh [OUT_DIR] [extra flags, e.g. --mock]
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
OUT=${1:-runs/pilot_s3}; [ $# -gt 0 ] && shift  # (a bare "shift" with no arguments exits dash)
LOG=$OUT/logs; mkdir -p $LOG
COMMON="--arms P0,PF,PE,PT,PC --seeds 100-101 --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --max-tokens 512 --out $OUT $*"
run() { # model slug cap
  python -m sting.run --subject-model $1 --cap-usd $3 --workers 5 $COMMON > $LOG/$2.log 2>&1 &
}
run mistralai/ministral-14b-2512 m14 0.80
run qwen/qwen3.5-9b              q9  0.60
run mistralai/ministral-8b-2512  m8  0.60
wait
