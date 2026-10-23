#!/bin/sh
# Study 1 restart pilot (Addendum 3): seeds >= 100, excluded from results
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
for m in qwen/qwen3.5-9b mistralai/ministral-14b-2512 mistralai/ministral-8b-2512; do
  python -m sting.run --arms C0 --seeds 100-102 --subject-model $m --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --out runs/pilot_s1v2 --cap-usd 0.5 --workers 3 &
  python -m sting.run --arms C3 --seeds 100-101 --subject-model $m --agent-model google/gemma-3-12b-it --no-reasoning-models qwen/qwen3.5-9b --out runs/pilot_s1v2 --cap-usd 0.5 --workers 2 &
done
wait
