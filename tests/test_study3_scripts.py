"""Study 3 analysis scripts: crash handling and the pre-registered decision rule."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyse_study3 as S3  # noqa: E402

from sting.arms import ARMS
from sting.engine import Game
from sting.llm import MockLLM

MODELS = {"T": "m-t", "X": "m-x", "H": "m-h", "S": "m-s"}


def _write_game(root: Path, arm: str, seed: int) -> Path:
    path = root / "study3" / arm / "m_t" / f"seed{seed:04d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        Game(ARMS[arm], MODELS, MockLLM(seed=seed), seed, lambda r: fh.write(json.dumps(r) + "\n")).play()
    return path


def test_loader_counts_empty_and_cut_off_logs_as_crashed(tmp_path):
    good = _write_game(tmp_path, "P0", 1)
    (good.parent / "seed0002.jsonl").write_text("")  # empty log
    cut = _write_game(tmp_path, "P0", 3)
    cut.write_text(cut.read_text()[:400])  # cut off mid-game: header kept, no game_end
    d, games = S3.load(tmp_path)
    assert sorted(games.seed) == [1, 2, 3]
    assert games.set_index("seed").ended.to_dict() == {1: True, 2: False, 3: False}
    assert set(d.seed) == {1}


def _synthetic(changes: dict[str, tuple[float, float]], n: int = 40) -> pd.DataFrame:
    """Decisions with given pass rates (partner, S) per arm; P0: (0.95, 0.60)."""
    rng = np.random.default_rng(1)
    rows = []
    for arm, (p_partner, p_s) in {"P0": (0.95, 0.60), **changes}.items():
        for g in range(n):
            for judge in ("T", "X"):
                for kind, p in (("partner", p_partner), ("S", p_s)):
                    for _ in range(4):
                        rows.append({"game": f"{arm}|m|{g}", "model": "m", "arm": arm, "judge": judge, "kind": kind,
                                     "pass_": int(rng.random() < p)})
    return pd.DataFrame(rows)


def test_a_change_carried_only_by_the_decoy_does_not_count_as_breaking_the_pact():
    x = _synthetic({"PF": (0.95, 0.95), "PE": (0.95, 0.60), "PT": (0.60, 0.60), "PC": (0.95, 0.60)})
    res = S3.primary_tests(x, perms=300, rng=np.random.default_rng(2))
    assert res["PF"]["p_holm"] < 0.05 and res["PF"]["est"] < 0  # favouritism fell, but only via S
    assert not res["PF"]["breaks_pact"] and not res["PF"]["backfire"]
    assert res["PT"]["breaks_pact"]  # the partners stopped protecting each other
    assert not res["PE"]["breaks_pact"]
