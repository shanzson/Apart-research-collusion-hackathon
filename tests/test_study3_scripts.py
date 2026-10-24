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


def test_skip_done_replays_only_unfinished_games_and_keeps_their_logs(tmp_path, capsys):
    from sting import run as R
    out = tmp_path / "runs"
    base = ["--arms", "P0,PE", "--seeds", "0-1", "--mock", "--no-interview", "--workers", "2", "--out", str(out)]
    assert R.main(base) == 0
    logs = sorted((out / "study3").glob("*/*/seed*.jsonl"))
    assert len(logs) == 4
    cut = out / "study3" / "PE" / R.slug("mock-subject") / "seed0001.jsonl"
    lines = cut.read_text().splitlines()
    cut.write_text("\n".join(lines[:5]) + '\n{"type": "note", "fr')  # stopped mid-game, last line cut off
    finished = {p: p.read_text() for p in logs if p != cut}
    capsys.readouterr()
    assert R.main(base + ["--skip-done"]) == 0
    assert '{"skip_done": 3, "to_run": 1}' in capsys.readouterr().out
    assert all(p.read_text() == text for p, text in finished.items())  # finished games untouched
    assert any(json.loads(l).get("type") == "game_end" for l in cut.read_text().splitlines())  # replayed
    kept = list((tmp_path / "runs_failed").glob("*/study3/PE/*/seed0001.jsonl"))
    assert len(kept) == 1 and kept[0].read_text().endswith('"fr')


def _mock_pilot(root: Path) -> None:
    from sting import run as R
    assert R.main(["--arms", "P0,PF,PE,PT,PC", "--seeds", "100-101", "--mock", "--no-interview", "--workers", "4",
                   "--out", str(root)]) == 0


def test_pilot_check_matches_labels_to_notes_and_gates_post_pact_pitching(tmp_path):
    import csv
    import classify_study3 as C
    import study3_pilot_check as PC
    root = tmp_path / "runs"
    _mock_pilot(root)
    items = C.load_items(root, "notes", include_pilot=True)
    assert items and any(not it["pact"] for it in items if it["round"] >= 2)
    path = tmp_path / "labels.csv"

    def write(rows):
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["key", *rows[0][0].keys(), *C.NOTE_FLAGS, "parsed"])
            w.writeheader()
            for it, flags in rows:
                w.writerow({"key": C.item_key("notes", it), **it, **{k: k in flags for k in C.NOTE_FLAGS},
                            "parsed": True})

    def delivered(it):  # every approach note carries the whole point, nothing else carries anything
        return set(PC.LABEL_OF[it["arm"]]) if it["arm"] in PC.LABEL_OF and it["round"] >= 2 and it["pact"] \
            and (it["arm"] != "PC" or it["to"] == "X") else set()
    write([(it, delivered(it)) for it in items])
    PC.main([str(root), str(tmp_path / "out1"), "--notes-labels", str(path)])
    g = json.loads((tmp_path / "out1" / "pilot_checks.json").read_text())["G2_H_notes"]
    assert g["n_labels_missing"] == 0 and g["a_pass_judge"] and g["b_pass"] and g["b2_pass"] and g["c_pass"]
    assert "PACT_OVER" in (tmp_path / "out1" / "notes_for_reading.txt").read_text()
    # pitching after the pact is over fails b2 (and only b2)
    write([(it, delivered(it) | ({"one_winner"} if it["arm"] == "PT" and it["round"] >= 2 and not it["pact"] else set()))
           for it in items])
    PC.main([str(root), str(tmp_path / "out2"), "--notes-labels", str(path)])
    g = json.loads((tmp_path / "out2" / "pilot_checks.json").read_text())["G2_H_notes"]
    assert not g["b2_pass"] and g["b_pass"] and g["a_pass_judge"]
    # labels from another run (different text) do not count: the check is incomplete, not passed
    write([({**it, "text": it["text"] + " (other run)"}, delivered(it)) for it in items])
    PC.main([str(root), str(tmp_path / "out3"), "--notes-labels", str(path)])
    g = json.loads((tmp_path / "out3" / "pilot_checks.json").read_text())["G2_H_notes"]
    assert g["n_labels_missing"] == len(items) and not (g["a_pass_judge"] or g["b_pass"] or g["b2_pass"] or g["c_pass"])


def test_hand_sample_of_notes_draws_only_where_an_approach_can_be_due(tmp_path):
    import csv
    import classify_study3 as C
    root = tmp_path / "runs"
    _mock_pilot(root)
    out = tmp_path / "hand.csv"
    assert C.main([str(root), "--task", "notes", "--include-pilot", "--hand-sample", "40", "--out", str(out)]) == 0
    key = list(csv.DictReader((tmp_path / "hand_KEY.csv").open()))
    items = {C.item_key("notes", it): it for it in C.load_items(root, "notes", include_pilot=True)}
    drawn = [items[k["key"]] for k in key]
    assert drawn and all(it["round"] >= 2 and it["pact"] and (it["arm"] != "PC" or it["to"] == "X") for it in drawn)
    assert {it["arm"] for it in drawn} == {"P0", "PF", "PE", "PT", "PC"}
