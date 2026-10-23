#!/bin/sh
# Study 2 series follow-up: exact command from prereg/ADDENDUM_2_series.md
cd /home/user/Apart-research-collusion-hackathon
export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt
exec python -m sting.run --arms A0F,A1F --seeds 0-9 --series-games 20 --offer-game 15 --subject-model mistralai/ministral-14b-2512 --x-model qwen/qwen3.5-9b --agent-model google/gemma-3-12b-it --s-model mistralai/ministral-8b-2512 --no-reasoning-models qwen/qwen3.5-9b --paper-sampling --max-tokens 512 --out runs/series --cap-usd 30 --workers 20
