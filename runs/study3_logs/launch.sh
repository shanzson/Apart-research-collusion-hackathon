#!/bin/sh
# Study 3 main run (prereg/ADDENDUM_4_study3.md): seeds 0-35, all five arms, three subject models (540 games).
# Caps are about 1.5x the expected cost per model and are revised from the pilot before launch.
# Usage: launch.sh [OUT_DIR] [extra flags, e.g. --mock]
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
OUT=${1:-runs/study3}; [ $# -gt 0 ] && shift  # (a bare "shift" with no arguments exits dash)
LOG=runs/study3_logs; [ "$OUT" != "runs/study3" ] && LOG=$OUT/logs; mkdir -p $LOG
COMMON="--arms P0,PF,PE,PT,PC --seeds 0-35 --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --max-tokens 512 --out $OUT $*"
run() { # model slug cap workers
  python -m sting.run --subject-model $1 --cap-usd $3 --workers $4 $COMMON > $LOG/$2.log 2>&1 &
}
run mistralai/ministral-14b-2512 m14 10.80 6
run qwen/qwen3.5-9b              q9  6.75  6
run mistralai/ministral-8b-2512  m8  6.50  6
wait
