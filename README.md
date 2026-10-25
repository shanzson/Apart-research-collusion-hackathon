# Decoy-controlled stings in Liar's Bar

Apart Research AI Collusion Research Sprint (Oct 23-25, 2026), research question 3.2: can a trusted agent that
offers to collude expose or disrupt collusion between AI agents?

## What this runs
- **Study 1 (primary).** A trusted AI agent **H** (a model under a mission system prompt) privately approaches the
  two agents under test (**T**, **X**) with a benign request, an indirect hint, or a direct non-challenge pact.
  A decoy **S** (same model, same system prompt minus the mission) sends only small talk. We measure whether the
  agents go easier on H than on S, what they say, and whether they later deny any agreement.
- **Study 2 (positive control).** The paper's designer-offered secret channel between T and X (V0 wording).
- **Study 3 (breaking a pact; `prereg/ADDENDUM_4_study3.md`).** T and X start every game with a secret pact; from round 2
  H tries one of four approaches to break it (P0 control, PF fairness appeal, PE exposure, PT temptation, PC
  counter-offer). Two 30-game pilots, then a 540-game main run (25 October 2026).

Game rules, scoring and prompts follow Zeng & Rudzicz (2026), "Voluntary Collusion with Secret Tools in Competing
LLM Agents" (arXiv 2605.27593), and the starter repository AgentSafety2025/LLM-Agent-collusion. Deviations are
listed at the top of `sting/engine.py` and in `sting/prompts.py` (each text is tagged PAPER, REPO or OURS).

## Layout
- `sting/engine.py`: the game; `sting/prompts.py`: every prompt with provenance; `sting/arms.py`: conditions
- `sting/llm.py`: OpenRouter client (key from `OPENROUTER_API_KEY` only; per-process spend cap) and a mock
- `sting/run.py`: runs games, one JSONL log per game
- `tests/`: rule tests with mock players (no API needed): `python -m pytest -q tests`
- `.github/workflows/run_games.yml`: manually triggered runs on GitHub Actions using the repository secret
- `scripts/`: model-ID check, matrix builder, quick summary

## Running
Locally without an API key: `python -m sting.run --arms C0,C3 --seeds 0-1 --mock --out runs/mock`.
On GitHub: Actions -> run-games -> Run workflow, choose arms, seeds and models. Logs are uploaded as artifacts.
