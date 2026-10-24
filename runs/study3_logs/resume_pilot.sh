#!/bin/sh
# Study 3 pilot, resumed after a container restart stopped launch_pilot.sh: 11 of the 30 games had ended, 15 logs
# were cut off and 4 games had not started. This runs only those 19, with the pilot's settings; the cut-off logs are
# copied to runs/pilot_s3_failed/<time>/ first, because a rerun overwrites them. Usage: resume_pilot.sh (real run only)
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
OUT=runs/pilot_s3; LOG=$OUT/logs; KEEP=runs/pilot_s3_failed/$(date -u +%Y%m%dT%H%M%S)
for f in $(find $OUT/study3 -name 'seed*.jsonl'); do
  grep -q '"game_end"' $f || { mkdir -p $KEEP/$(dirname ${f#$OUT/}); cp -p $f $KEEP/${f#$OUT/}; }
done
COMMON="--agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --max-tokens 512 --workers 5 --out $OUT $*"
run() { # model arms seeds cap logname
  python -m sting.run --subject-model $1 --arms $2 --seeds $3 --cap-usd $4 $COMMON > $LOG/$5.log 2>&1 &
}
run mistralai/ministral-14b-2512 P0,PF,PE,PT,PC 101     0.60 m14_resume_101
run mistralai/ministral-14b-2512 PC             100     0.20 m14_resume_PC100
run qwen/qwen3.5-9b              P0,PF,PE       100-101 0.60 q9_resume_100-101
run qwen/qwen3.5-9b              PT,PC          101     0.30 q9_resume_101
run mistralai/ministral-8b-2512  P0,PF,PE,PT,PC 101     0.50 m8_resume_101
wait
