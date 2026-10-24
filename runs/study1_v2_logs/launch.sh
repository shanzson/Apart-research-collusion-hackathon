#!/bin/sh
# Study 1 restart main run (Addendum 3, final allocation). Usage: launch.sh [OUT_DIR] [extra flags, e.g. --mock]
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
OUT=${1:-runs/study1_v2}; [ $# -gt 0 ] && shift  # (a bare "shift" with no arguments exits dash)
LOG=runs/study1_v2_logs; [ "$OUT" != "runs/study1_v2" ] && LOG=$OUT/logs; mkdir -p $LOG
COMMON="--agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --out $OUT $*"
run() { # model slug arms seeds cap workers
  python -m sting.run --subject-model $1 --arms $3 --seeds $4 --cap-usd $5 --workers $6 $COMMON > $LOG/$2_$(echo $3 | tr , -).log 2>&1 &
}
run mistralai/ministral-14b-2512 m14 C0      0-23 1.25 3
run mistralai/ministral-14b-2512 m14 B,C2,C3 0-47 7.80 8
run mistralai/ministral-14b-2512 m14 C3NE    0-11 0.70 2
run qwen/qwen3.5-9b              q9  C0      0-23 1.00 3
run qwen/qwen3.5-9b              q9  B,C2,C3 0-47 5.20 10
run qwen/qwen3.5-9b              q9  C3NE    0-11 0.50 2
run mistralai/ministral-8b-2512  m8  C0      0-23 0.70 3
run mistralai/ministral-8b-2512  m8  B,C2,C3 0-47 4.50 6
run mistralai/ministral-8b-2512  m8  C3NE    0-11 0.40 2
wait
