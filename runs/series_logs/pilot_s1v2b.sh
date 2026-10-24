#!/bin/sh
# Study 1 restart mini-pilot 2 (Addendum 3): revised B and C2 wording, same seeds as mini-pilot 1, excluded
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
for m in mistralai/ministral-14b-2512 qwen/qwen3.5-9b; do
  python -m sting.run --arms B,C2 --seeds 100-101 --subject-model $m --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --out runs/pilot_s1v2b --cap-usd 0.5 --workers 4 &
done
wait
