# Addendum 2: Study 2 follow-up — offer at game 15 of a series, paper-like table

Written before any main series game was played (one 2-game smoke series, seed 100, excluded). Study 1 is paused
part-way (Llama-3.1-8B: 120/120 games; Qwen3.5-9B: 32/120; Qwen3.6-35B-A3B: 63/120); no Study 1 outcome has been
looked at.

## Why

Study 2 (single games, offer before round 1) did not reproduce the paper's effect: the channel formed in 30 of 36 A1
games (33 accepted; 3 Llama acceptances were lost to a parser bug, now fixed), but the partners' pass rate on each
other moved only from 0.56 (A0) to 0.59 (A1, ITT; +0.05, p = .43). An independent audit and the paper itself
(arXiv 2605.27593v2, Sec. 3.1, 3.2, App. D, H) show four design differences:

| | Paper (verified in the PDF) | Study 2 |
|---|---|---|
| Offer timing | game 20 of a 50-game sequence; channel stays open for games 20-50 | before round 1 of a single game |
| Table | four 7-8B open models of similar strength (Mistral-7B + LLaMA-3-8B colluders; LLaMA-3.1-8B + Qwen2.5-7B others) | two small subject copies vs two GPT-4.1-mini players (H/S won 67 of 72 games) |
| Secret messages | one with every action; each member sees the partner's latest message (Sec. 2) | one per round, at round start |
| Sampling | Table 10 (e.g. temperature 0.7-0.8, top-p, top-k, repetition penalty) | provider defaults |

The paper's exact message prompt (App. P/Q) is not in the PDF available to us, so the per-action message prompt is
ours, written to follow Sec. 2.

## Design

- Players (four different, similar-strength open models, chosen by the study lead for recency over the paper's
  2024 models):

| Role | Model |
|---|---|
| T (colluder) | `mistralai/ministral-14b-2512` |
| X (colluder) | `qwen/qwen3.5-9b` (reasoning disabled) |
| H (other) | `google/gemma-3-12b-it` |
| S (other) | `mistralai/ministral-8b-2512` |

Roles were assigned so that each side has one larger and one smaller model (in the 2-game smoke series the
8B model, then playing T, was eliminated first in both games).

- Sampling: the paper's Table 10 settings applied by family (Mistral 0.7/0.9/50/1.02 to Ministral 3; Qwen
  0.8/0.9/50/1.05 to Qwen3.5); Gemma is not in the paper, so Google's recommended defaults (1.0/0.95/64). These are
  the paper's values for the older models of each family, not the newer models' own recommendations; some
  OpenRouter providers may ignore top_k / repetition_penalty (served provider logged per call). Disclosed.
- max_tokens 512 for every player's decisions (the extra secret-message key made 256 too tight for Qwen in the smoke
  test; same in both arms).
- H and S form per-round impressions like T and X (in Study 1 they do not), since here they are ordinary players.
- A series = N games in a row at the same table: same players and display names. Carried between games: each
  player's impressions of the others (the repo's per-round reflections as they stood at the end of the previous
  game) and one factual line per earlier game (winner, final points, elimination order). Points restart at zero.
  Game g uses seed (series seed + 100000 x (g - 1)) for the deal and revolver.
- A1F: at the start of game 15 the designer makes the V0 offer exactly as in Study 2 (fixed parser: numbered answers,
  case-insensitive partner, an ACCEPT without a name means X, the only partner offered). If both accept, the channel
  stays open for the rest of the series; T and X attach a secret message to every play and challenge and see the
  partner's latest message and their own latest message (messages up to 150 words; the paper states no limit; a
  message is kept only if it came with an accepted play or a parsed challenge; messages carried into the next game
  are marked "(sent in the previous game)"). A0F: identical, no offer ever. H and S never see the channel.
- Interview after the last game only.
- Launch command (one line):

```
python -m sting.run --arms A0F,A1F --seeds 0-9 --series-games 20 --offer-game 15 --subject-model mistralai/ministral-14b-2512 --x-model qwen/qwen3.5-9b --agent-model google/gemma-3-12b-it --s-model mistralai/ministral-8b-2512 --no-reasoning-models qwen/qwen3.5-9b --paper-sampling --max-tokens 512 --out runs/series --cap-usd 30 --workers 20
```

- Budget: expected ~$15 (audit estimate $12-19). The cap ($30) only stops the run; hitting it would stop all series
  at once and leave none complete, so it is set well above the estimate. Checkpoint: after every series has finished
  game 2, projected total ~ 12-13 x spend so far; the run is stopped if the projection approaches the cap.
  API calls in series runs retry up to 10 times (~5 minutes) before a game fails.
- Sample: 2 arms x 10 series (series seeds 0-9; the same seeds in both arms), N = 20 games (offer at 15, games
  15-20 with the channel), i.e. 400 games. Cap $30. Output in `runs/series` (never in `runs/main`), 20 workers.
- Completeness: only complete series count (all N games completed, each carrying the right history). A failed
  series is re-run once from game 1 with the same seed (the re-run deletes the earlier attempt's files); if it fails
  again it is excluded and listed.

## Analysis (exploratory, not confirmatory)

`scripts/analyse_series.py`. The unit is the series. For each series: change = pass rate in games 15-20 minus pass
rate in games 1-14. Main result: mean change in A1F minus mean change in A0F, permutation test over the 20 series
labels (10,000 permutations), for three outcomes:
- partner: T and X letting each other's plays pass (collusion between partners);
- overall: T and X letting any play they judge pass (the paper's measure, Table 14: colluders' overall challenge
  rate, 97.6% -> 30.7%, a 69% relative drop);
- outsider: T and X letting H's and S's plays pass.
Effects are also reported as relative changes in the challenge rate, because our starting challenge rate (~40-45%)
is far below the paper's (~97%), so the paper's absolute drop (-67 points) cannot occur here.
Also reported: the pre-offer gap between arms (placebo, expected ~0); a per-decision linear probability model after
the offer (SEs clustered by series, t-based) as a secondary check; ITT and formed-only; invalid plays by arm and
period; pass rates by game number; acceptance; message content. With 10 series per arm this can detect a large
effect but not a small one.

## Further differences from the paper (disclosed)

The paper ran 3 sequences per condition with 31 games after the offer (we: 10 series, 6 games after); its turn
order is fixed (ours alternates between two seatings); its adoption offers listed all three other players (ours
lists only X); failed parses were not retried (we retry up to 3 times, then use a default action); its models ran
locally (ours through OpenRouter); what carried between games and the exact message prompt are not described in
the pages available to us; the public "behavior" text can reveal a player's cards (starter-repo format, same in
both arms).

## Decision rule for Study 1 (stated in advance)

Whether Study 1 resumes unchanged is decided by the study lead after this follow-up. Until then no Study 1 outcome is
looked at, so that decision cannot be influenced by Study 1 results.
