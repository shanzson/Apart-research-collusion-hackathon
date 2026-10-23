# Addendum 3: Study 1 restarts with new models

Date: 23 October 2026.

## Decision

The study lead decided to stop using `openai/gpt-4.1-mini` (cost) and to restart Study 1 from scratch with:

| Role | Model |
|---|---|
| H (trusted agent) and S (decoy), same model as before by design | `google/gemma-3-12b-it` |
| Subjects (T and X, same model in both seats), one model per set of games | `qwen/qwen3.5-9b` (reasoning disabled), `mistralai/ministral-14b-2512`, `mistralai/ministral-8b-2512` |

A second reason: in Study 2 the GPT-4.1-mini players won 67 of 72 games, i.e. they were far stronger than the subjects,
which shortens the subjects' exposure to H.

## Timing and blinding (stated honestly)

The decision was made before any Study 1 outcome had been looked at. After the decision, on the same day, the study
lead viewed the results of the first attempt. The restart's design below was fixed at the time of the decision and is
not changed because of those results.

## What stays the same

Arms (C0, B, C2, C3, C3NE), 24 seeds per arm and model (0-23), hypotheses, tests, exclusions and the analysis script
`scripts/analyse.py` (unchanged, hash in `FREEZE.txt`), prompts and game rules. Decoding: per-model max_tokens table
(Qwen 256, Mistral 512, Gemma 512) and provider-default sampling, as pre-registered for Study 1 (the paper-sampling
option used in the Study 2 follow-up is not used here).

## The first attempt

215 completed games (Llama-3.1-8B 120, Qwen3.5-9B 32, Qwen3.6-35B-A3B 63; GPT-4.1-mini as H and S) in
`runs/main/study1` are kept and reported only as a trial run, not as Study 1 results.

## Before the main run

1. Pilot (seeds >= 100, excluded): per subject model C0 x 3 + C3 x 2 in `runs/pilot_s1v2`. Gates: pass rates on H and
   S not near 0 or 1; invalid decisions < 5%; Gemma plays H's role (makes the offer in C3, does not reveal its mission
   or cards).
2. Independent audit, then the study lead's approval.
3. Main run into `runs/study1_v2` (never into `runs/main`).
