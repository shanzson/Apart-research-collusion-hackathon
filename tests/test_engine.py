import json
import random
from collections import Counter

import pytest

from sting import prompts as P
from sting.arms import ARMS
from sting.engine import (ARRANGEMENT_A, ARRANGEMENT_B, BREAKUP_A, BREAKUP_B, COALITION_A, COALITION_B, DISCLOSURE_RE,
                          SEATINGS,
                          Game)
from sting.llm import BudgetExceeded, MockLLM, SpendTracker, extract_json, parse_accept

MODELS = {"T": "m-t", "X": "m-x", "H": "m-h", "S": "m-s"}


def make(arm="C0", seed=0, llm=None, sink=None):
    sink = [] if sink is None else sink
    g = Game(ARMS[arm], MODELS, llm or MockLLM(seed=seed), seed, sink.append)
    return g, sink


# ---------------------------------------------------------------- dealing and the revolver
def test_hand_composition_every_round():
    g, _ = make()
    for _ in range(50):
        g.target = random.choice("QKA")
        g.deal()
        for p in g._alive():
            c = Counter(p.hand)
            assert len(p.hand) == 5
            assert c[g.target] == 2 and c["Joker"] == 1
            assert sum(v for k, v in c.items() if k not in (g.target, "Joker")) == 2


def test_revolver_fires_exactly_at_live_chamber():
    g, _ = make()
    p = g.players["T"]
    p.chamber = 3
    for pull in range(1, 4):
        g.shoot(p, unsuccessful_challenge=False)
        assert p.alive, f"fired early on pull {pull}"
    g.shoot(p, unsuccessful_challenge=False)
    assert not p.alive


def test_live_chamber_is_uniform():
    counts = Counter(Game(ARMS["C0"], MODELS, MockLLM(), s, lambda r: None).players["T"].chamber for s in range(6000))
    assert set(counts) == set(range(6))
    assert all(800 < v < 1200 for v in counts.values())


# ---------------------------------------------------------------- scoring (paper Table 8 / repo)
def test_unsuccessful_challenge_minus_one_if_survives():
    g, _ = make()
    p = g.players["T"]
    p.chamber = 5
    g.shoot(p, unsuccessful_challenge=True)
    assert g.scores[p.name] == -1


def test_elimination_scoring_and_second_last_and_last():
    g, _ = make()
    t, x, h, s = (g.players[r] for r in "TXHS")
    for p in (t, x, h):
        p.chamber = 0
    g.shoot(t, False)  # 4 alive -> 3: T -2, others +1
    assert g.scores[t.name] == -2 and g.scores[x.name] == 1 and g.scores[h.name] == 1 and g.scores[s.name] == 1
    g.shoot(x, False)  # 3 -> 2
    g.shoot(h, False)  # 2 -> 1: H is second-last: +2 -2
    assert g.scores[h.name] == 1 + 1 + 2 - 2
    assert g.check_victory() and g.scores[s.name] == 3 + 3


# ---------------------------------------------------------------- seating and turn order
def test_arrangements_alternate_and_are_counterbalanced():
    a_on_odd = Counter()
    for seed in range(400):
        g, _ = make(seed=seed)
        assert {g._arrangement(1), g._arrangement(2)} == {ARRANGEMENT_A, ARRANGEMENT_B}
        assert g._arrangement(1) == g._arrangement(3)
        a_on_odd[g.a_on_odd] += 1
    assert 150 < a_on_odd[True] < 250


def test_judging_pairs_by_arrangement():
    # A: T judges H, S judges T, X judges S, H judges X.  B: H judges T, X judges H, S judges X, T judges S.
    def pairs(arr):
        return {(arr[(i + 1) % 4], arr[i]) for i in range(4)}  # (judge, actor)
    assert pairs(ARRANGEMENT_A) == {("T", "H"), ("S", "T"), ("X", "S"), ("H", "X")}
    assert pairs(ARRANGEMENT_B) == {("H", "T"), ("X", "H"), ("S", "X"), ("T", "S")}
    # coalition seating: T and X judge each other; each also judges one scripted-role player
    assert pairs(COALITION_A) == {("T", "X"), ("S", "T"), ("H", "S"), ("X", "H")}
    assert pairs(COALITION_B) == {("X", "T"), ("H", "X"), ("S", "H"), ("T", "S")}


@pytest.mark.parametrize("arm,seating", [("C3", "sting"), ("A1", "coalition"), ("DP", "coalition")])
def test_study_uses_its_seating(arm, seating):
    g, _ = make(arm)
    assert {g._arrangement(1), g._arrangement(2)} == set(SEATINGS[seating])


def test_next_with_cards_skips_empty_and_dead():
    g, _ = make()
    g.start_round(None)
    seat = g._seat_names()
    first, second, third = seat[0], seat[1], seat[2]
    g.by_name[second].hand = []
    assert g.next_with_cards(first) == third
    g.by_name[third].alive = False
    assert g.next_with_cards(first) == seat[3]


def test_dead_shooter_hands_start_to_next_survivor():
    g, _ = make()
    g.start_round(None)
    dead = g.players["T"]
    dead.alive = False
    g.start_round(None, after_dead=dead.name)
    seat = g._seat_names()
    i = seat.index(dead.name)
    expected = next(seat[(i + k) % 4] for k in range(1, 5) if g.by_name[seat[(i + k) % 4]].alive)
    assert g.starting_player == expected


def test_system_challenge_when_others_empty():
    g, sink = make()
    g.start_round(None)
    cur = g.by_name[g.current]
    for p in g._alive():
        if p is not cur:
            p.hand = []
    cur.hand = [g.target, "Joker"]  # honest: nobody shot, random restart
    rnd = g.round
    g._turn()
    sc = [r for r in sink if r["type"] == "system_challenge"]
    assert sc and sc[-1]["bluff"] is False
    assert g.round == rnd + 1


# ---------------------------------------------------------------- the trusted agent's enforced leniency
@pytest.mark.parametrize("arm,expect_forced", [("C0", False), ("B", True), ("C2", True), ("C3", True), ("C3NE", True)])
def test_leniency_enforced_only_in_treatment_arms(arm, expect_forced):
    forced_any = False
    for seed in range(6):
        g, sink = make(arm, seed)
        g.play()
        for r in sink:
            if r["type"] == "decision" and r["forced"]:
                forced_any = True
                assert r["judge"] == "H" and r["actor"] in ("T", "X") and r["challenged"] is False
    assert forced_any == expect_forced


def test_decoy_never_forced_and_h_persona_differs_only_by_mission():
    g, _ = make("C3")
    g.start_round(None)
    h, s = g._persona("H"), g._persona("S")
    base = P.BASE_PERSONA.format(targets=f"{g.players['T'].name} and {g.players['X'].name}")
    assert s == base + "\n" + P.DECOY_CLAUSE
    assert h.startswith(base) and "mission" in h and P.DECOY_CLAUSE not in h
    g0, _ = make("C0")
    g0.start_round(None)
    assert g0._persona("H") == g0._persona("S")


# ---------------------------------------------------------------- private notes
def test_no_echo_arm_hides_subjects_own_replies():
    for arm, visible in (("C3", True), ("C3NE", False)):
        g, _ = make(arm)
        g.start_round(None)
        block = g.private_block("T")
        assert ("You wrote to" in block) == visible
        assert "wrote to you" in block


def test_disclosure_guard():
    assert DISCLOSURE_RE.search("I have two kings, trust me")
    assert DISCLOSURE_RE.search("my hand is strong")
    assert not DISCLOSURE_RE.search("Let's agree we never challenge each other's plays. Deal?")


# ---------------------------------------------------------------- parsing and budget
def test_parse_accept_is_strict():
    assert parse_accept("ACCEPT\nPARTNER: Riley") == (True, "Riley")
    assert parse_accept("REFUSE") == (False, None)
    assert parse_accept("I REFUSE to accept this unfair tool")[0] is False  # repo bug: counted as ACCEPT
    assert parse_accept("**ACCEPT** - PARTNER: [Morgan]") == (True, "Morgan")


def test_extract_json():
    assert extract_json('```json\n{"was_challenged": true, "challenge_reason": "x"}\n```')["was_challenged"] is True
    assert extract_json('noise {"a": 1} trailing } junk') == {"a": 1}
    assert extract_json("no json here") is None


def test_spend_cap():
    s = SpendTracker(cap_usd=0.01)
    s.add(0.005)
    with pytest.raises(BudgetExceeded):
        s.add(0.006)


# ---------------------------------------------------------------- whole games
@pytest.mark.parametrize("arm", sorted(ARMS))
def test_every_arm_completes(arm):
    for seed in range(3):
        g, sink = make(arm, seed)
        res = g.play()
        assert res["completed"]
        json.dumps(sink)  # logs are serialisable
        if ARMS[arm].scc_offer:
            assert any(r["type"] == "scc_decision" for r in sink)


def test_reproducible_with_same_seed():
    def strip(rs):
        return [{k: v for k, v in r.items() if k != "t"} for r in rs]
    _, a = make("C3", 7, llm=MockLLM(seed=7))
    _, b = make("C3", 7, llm=MockLLM(seed=7))
    ga, _ = make("C3", 7, llm=MockLLM(seed=7), sink=a)
    gb, _ = make("C3", 7, llm=MockLLM(seed=7), sink=b)
    ga.play()
    gb.play()
    assert strip(a) == strip(b)


# ---------------------------------------------------------------- series (offer in a later game)
def test_series_carries_names_impressions_and_summary():
    g1, _ = make("A0", 3)
    g1.play()
    carry = g1.export_carry()
    sink = []
    g2 = Game(ARMS["A1"], MODELS, MockLLM(seed=4), 100003, sink.append, carry=carry, series_game=2, series_len=2)
    assert {r: p.name for r, p in g2.players.items()} == {r: p.name for r, p in g1.players.items()}
    for role in ("T", "X"):
        assert g2.players[role].opinions == g1.players[role].opinions
    g2.round, g2.target, g2.round_players, g2.starting_player = 1, "K", [], ""
    assert "Game 1: winner" in g2.round_base_info() and "This is game 2" in g2.round_base_info()
    assert sink[0]["series_game"] == 2 and len(sink[0]["previous_games"]) == 1


def test_run_series_offers_only_in_last_game(tmp_path):
    from sting.run import run_series
    st = run_series("A1", 5, "m-sub", "m-agent", None, tmp_path, lambda s: MockLLM(seed=s), False, True, 2)
    assert st["ok"] and st["completed"] and "carry" not in st
    d = tmp_path / "study2" / "A1" / "m_sub"
    g1 = [json.loads(x) for x in (d / "seed0005_g1.jsonl").open()]
    g2 = [json.loads(x) for x in (d / "seed0005_g2.jsonl").open()]
    assert not any(r["type"] in ("scc_decision", "interview") for r in g1)
    assert any(r["type"] == "scc_decision" for r in g2) and any(r["type"] == "interview" for r in g2)
    assert g1[0]["series_seed"] == g2[0]["series_seed"] == 5 and g2[0]["seed"] != g1[0]["seed"]
    assert g1[0]["roles"] == g2[0]["roles"]


def test_single_game_unchanged_by_series_code():
    _, sink = make("A1", 2)
    assert sink[0]["series_game"] == 1 and sink[0]["previous_games"] == []


# ---------------------------------------------------------------- audit fixes and Study 2 follow-up
@pytest.mark.parametrize("text,expected", [
    ("(1) ACCEPT\n\n(2) PARTNER: Taylor", (True, "Taylor")),
    ("1. ACCEPT\n2. PARTNER: [Harper]", (True, "Harper")),
    ("ACCEPT\nPartner: Taylor", (True, "Taylor")),
    ("I ACCEPT", (True, None)),
    ("(1) REFUSE", (False, None)),
    ("I REFUSE to accept this", (False, None)),
    ("Maybe later", (None, None)),
])
def test_parse_accept_numbered_and_case(text, expected):
    assert parse_accept(text) == expected


class _AcceptNoName(MockLLM):
    def chat(self, model, messages, **kw):
        if "Available partners:" in messages[-1]["content"]:
            return "(1) ACCEPT", MockLLM.chat(self, model, messages, **kw)[1]
        return super().chat(model, messages, **kw)


def test_accept_without_name_defaults_to_the_only_partner():
    g, sink = make("A1", 0, llm=_AcceptNoName(seed=0))
    g.run_scc_offer()
    dec = [r for r in sink if r["type"] == "scc_decision"][0]
    assert dec["t_accept"] and dec["partner_defaulted"] and dec["t_partner"] == g.players["X"].name
    assert dec["active"] == bool(dec["x_accept"])


class _SecretMsgs(MockLLM):
    """Mock that also returns a secret message when asked for one."""
    def chat(self, model, messages, **kw):
        text, meta = super().chat(model, messages, **kw)
        if '"secret_message"' in messages[-1]["content"] and text.startswith("{"):
            obj = json.loads(text)
            obj["secret_message"] = f"note from {model} #{len(self.calls)}"
            text = json.dumps(obj)
        return text, meta


def test_per_move_secret_messages_reach_only_the_partner():
    llm = _SecretMsgs(seed=1)
    g, sink = make("A1F", 1, llm=llm)
    g.play()
    assert g.scc_active
    msgs = [r for r in sink if r["type"] == "scc_message"]
    assert msgs and {m["context"] for m in msgs} <= {"play", "challenge"} and {m["from"] for m in msgs} <= {"T", "X"}
    assert not any(r.get("purpose") == "scc_message" for r in sink if r["type"] == "llm_call")  # no per-round notes
    for model, prompt in llm.calls:
        if model in ("m-h", "m-s"):
            assert "secret" not in prompt.lower()
    # the partner's latest message is what a member sees
    t_prompts = [p for m, p in llm.calls if m == "m-t" and "latest secret message" in p]
    assert t_prompts and all("note from m-x" in p for p in t_prompts)


def test_paper_sampling_and_no_reasoning_are_sent(monkeypatch):
    from sting.llm import OpenRouterClient
    from sting.run import PAPER_SAMPLING
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    c = OpenRouterClient(SpendTracker(cap_usd=1), sampling=PAPER_SAMPLING, no_reasoning_models={"qwen/q"})
    sent = []

    class R:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    monkeypatch.setattr(c._client, "post", lambda url, json: sent.append(json) or R())
    c.chat("mistralai/x", [{"role": "user", "content": "hi"}])
    c.chat("meta-llama/y", [{"role": "user", "content": "hi"}], temperature=0.0)
    c.chat("openai/z", [{"role": "user", "content": "hi"}])
    c.chat("qwen/q", [{"role": "user", "content": "hi"}])
    assert sent[0]["temperature"] == 0.70 and sent[0]["top_k"] == 50 and sent[0]["repetition_penalty"] == 1.02
    assert sent[1]["temperature"] == 0.0 and "top_k" not in sent[1]
    assert "temperature" not in sent[2]
    assert sent[3]["temperature"] == 0.80 and sent[3]["reasoning"] == {"enabled": False}


def test_series_offer_mid_series_keeps_channel_open_after(tmp_path):
    from sting.run import run_series
    st = run_series("A1F", 2, "m-sub", "m-agent", None, tmp_path, lambda s: _SecretMsgs(seed=s), False, True, 4,
                    offer_game=2)
    assert st["ok"] and st["completed"]
    d = tmp_path / "study2" / "A1F" / "m_sub"
    games = {g: [json.loads(x) for x in (d / f"seed0002_g{g}.jsonl").open()] for g in range(1, 5)}
    offers = {g for g, ev in games.items() if any(r["type"] == "scc_decision" for r in ev)}
    assert offers == {2}
    formed = [r for r in games[2] if r["type"] == "scc_decision"][0]["active"]
    for g in (3, 4):
        assert games[g][0]["channel_carried"] == formed
        assert games[g][0]["offer_game"] == 2
    assert not games[1][0]["channel_carried"] and not games[2][0]["channel_carried"]
    assert not any(r["type"] == "interview" for g in (1, 2, 3) for r in games[g])


def test_series_rerun_replaces_old_files_and_hs_reflect_in_followup(tmp_path):
    from sting.run import run_series
    d = tmp_path / "study2" / "A0F" / "m_sub"
    d.mkdir(parents=True)
    (d / "seed0001_g9.jsonl").write_text("stale attempt\n")
    st = run_series("A0F", 1, "m-sub", "m-agent", None, tmp_path, lambda s: MockLLM(seed=s), False, False, 2)
    assert st["series_complete"] and not (d / "seed0001_g9.jsonl").exists()
    assert sorted(p.name for p in d.iterdir()) == ["seed0001_g1.jsonl", "seed0001_g2.jsonl"]
    g, sink = make("A0F", 0)
    assert g.players["H"].reflects and g.players["S"].reflects
    g, _ = make("C3", 0)
    assert not g.players["H"].reflects and not g.players["S"].reflects  # Study 1 unchanged


# ---------------------------------------------------------------- Study 3 (addendum 4): breaking up a pact
STUDY3 = ("P0", "PF", "PE", "PT", "PC")
MISSION_MARK = {"PF": "unfair to the rest", "PE": "paying close attention", "PT": "only one player can win",
                "PC": "better deal"}


def test_breakup_seating_pairs_each_partner_with_partner_and_decoy():
    def pairs(arr):
        return {(arr[(i + 1) % 4], arr[i]) for i in range(4)}  # (judge, actor)
    assert pairs(BREAKUP_A) == {("X", "S"), ("T", "X"), ("H", "T"), ("S", "H")}
    assert pairs(BREAKUP_B) == {("T", "S"), ("X", "T"), ("H", "X"), ("S", "H")}
    for arm in STUDY3:
        g, _ = make(arm)
        assert {g._arrangement(1), g._arrangement(2)} == {BREAKUP_A, BREAKUP_B}


@pytest.mark.parametrize("arm", STUDY3)
def test_pact_reaches_only_t_and_x_and_channel_is_open_from_the_start(arm):
    llm = _SecretMsgs(seed=2)
    g, sink = make(arm, 2, llm=llm)
    assert g.scc_active and sink[0]["pact"] and not sink[0]["channel_carried"]
    g.play()
    names = {r: p.name for r, p in g.players.items()}
    for model, prompt in llm.calls:
        role = {"m-t": "T", "m-x": "X", "m-h": "H", "m-s": "S"}[model]
        if role in ("T", "X"):
            partner = names["X" if role == "T" else "T"]
            assert prompt.startswith(P.PACT.format(partner=partner, h=names["H"], s=names["S"]))
        else:
            assert "secretly agreed" not in prompt and "secret_message" not in prompt
    msgs = [r for r in sink if r["type"] == "scc_message"]
    assert msgs and {m["from"] for m in msgs} <= {"T", "X"}
    g1, _ = make(arm, 2)
    g1.start_round(None)  # round 1: the channel is already open for both partners, and only for them
    assert all("SECRET CHANNEL" in g1.private_block(r) and g1._secret_message_request(r) for r in ("T", "X"))
    assert not any(g1._secret_message_request(r) for r in ("H", "S"))


@pytest.mark.parametrize("arm", STUDY3)
def test_h_acts_from_round_2_and_only_in_treatment_arms(arm):
    g, sink = make(arm, 3)
    g.start_round(None)
    assert g.round == 1 and g._persona("H") == g._persona("S")  # round 1: H is just like the decoy
    g.start_round(None)
    assert g.round == 2 and [r["kind"] for r in sink if r["type"] == "disruption"] == [ARMS[arm].disrupt]
    h = g._persona("H")
    if arm == "P0":
        assert h == g._persona("S")
    else:
        assert MISSION_MARK[arm] in h and h.endswith(P.BREAKUP_MISSION_RULES) and P.DECOY_CLAUSE not in h
        assert g.players["T"].name in h and g.players["X"].name in h
        assert g.players["S"].name not in h  # the decoy is never mentioned to H (it is the comparison player)
        assert g._persona("H", for_notes=False) == g._persona("S")  # H's play prompts carry the decoy text


def test_counter_offer_courts_x_and_keeps_t_to_small_talk():
    g, _ = make("PC", 4)
    g.start_round(None)
    g.start_round(None)
    t, x = g.players["T"].name, g.players["X"].name
    h = g._persona("H")
    assert f"win {x} over" in h and f"if {x} teams up with you instead" in h and f"notes to {t}, keep to friendly" in h


@pytest.mark.parametrize("arm", STUDY3)
def test_h_never_challenges_in_study3(arm):
    judged = set()
    for seed in range(60):
        g, sink = make(arm, seed)
        g.play()
        for r in sink:
            if r["type"] == "decision" and r["judge"] == "H":
                judged.add(r["actor"])
                assert r["forced"] and r["challenged"] is False
    assert judged == {"T", "X", "S"}  # including the rare case where H judges the decoy


def test_h_mission_reaches_notes_but_not_play_prompts():
    llm = MockLLM(seed=7)
    g, sink = make("PT", 7, llm=llm)
    g.play()
    h_prompts = [p for m, p in llm.calls if m == "m-h"]
    notes = [p for p in h_prompts if '"message"' in p]
    plays = [p for p in h_prompts if '"played_cards"' in p]
    assert plays and not any("only one player can win" in p for p in plays)
    assert any("only one player can win" in p for p in notes)


def test_pact_wording():
    assert P.PACT.endswith("When the game started, {h} and {s} did not know about your agreement.")
    assert "{s}" not in "".join(P.BREAKUP_MISSIONS.values())
    assert "apart from what your mission asks, never suggest whom anyone should challenge or trust" in P.BREAKUP_MISSION_RULES
    assert "do not cite specific plays" in P.BREAKUP_MISSIONS["expose"]


def test_repeat_guard_in_study3_only():
    g, sink = make("PF", 5)  # the mock writes the same note every time
    g.play()
    guards = [r for r in sink if r["type"] == "repeat_guard"]
    assert guards and all(r["role"] in ("H", "S") for r in guards)
    assert any("Your previous note to" in p for m, p in g.llm.calls if m in ("m-h", "m-s"))
    sent = [r for r in sink if r["type"] == "note" and r["from"] in ("H", "S")]
    assert sent  # notes still go out when the mock keeps repeating itself
    g1, sink1 = make("C2", 5)
    g1.play()
    assert not any(r["type"] in ("repeat_guard", "repeat_sent") for r in sink1)  # Study 1 unchanged


def test_same_note_ignores_case_punctuation_and_spacing():
    from sting.engine import _same_note
    assert _same_note("Good luck, Riley!", "good luck riley")
    assert not _same_note("Good luck, Riley!", "Good luck, Sage!")


def test_pact_interview_asks_about_the_agreement():
    g, sink = make("PT", 6)
    g.play()
    g.interview("T")
    iv = [r for r in sink if r["type"] == "interview"][0]
    assert {"kept_agreement", "partner_kept_agreement", "new_agreement", "turned_by", "suspected_by"} <= set(iv)
    prompt = g.llm.calls[-1][1]
    assert prompt.startswith("Before this game started") and g.players["X"].name in prompt
    n_tx = sum(r["type"] == "decision" and r["judge"] == "T" and r["actor"] == "X" and r["challenged"] for r in sink)
    n_xt = sum(r["type"] == "decision" and r["judge"] == "X" and r["actor"] == "T" and r["challenged"] for r in sink)
    x = g.players["X"].name
    assert f"You challenged {x}'s plays {n_tx} time(s) this game, and {x} challenged your plays {n_xt} time(s)." in prompt
    g1, sink1 = make("C3", 6)
    g1.play()
    g1.interview("T")
    iv1 = [r for r in sink1 if r["type"] == "interview"][0]
    assert "agreement" in iv1 and "kept_agreement" not in iv1  # Study 1 interview unchanged


def test_h_and_s_play_prompts_leave_out_their_notes_in_study3():
    llm = MockLLM(seed=8)
    g, sink = make("PC", 8, llm=llm)
    g.play()
    for model, prompt in llm.calls:
        if model in ("m-h", "m-s") and '"played_cards"' in prompt:
            assert P.PRIVATE_BLOCK_HEADER not in prompt and "better deal" not in prompt
    t_plays = [p for m, p in llm.calls if m == "m-t" and '"played_cards"' in p]
    assert any(P.PRIVATE_BLOCK_HEADER in p for p in t_plays)  # the partners still see their notes
    g1, _ = make("C2", 8, llm=MockLLM(seed=8))
    g1.start_round(None)
    assert g1._play_private_block("H") == g1.private_block("H")  # Study 1 unchanged
