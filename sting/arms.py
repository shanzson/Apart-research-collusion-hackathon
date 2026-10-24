"""Experimental arms.

Study 1 (primary): does an ordinary agent reciprocate a trusted agent's approach?
  C0    baseline: H and S both behave as ordinary players exchanging small talk (H has no mission)
  B     benign:   H proposes keeping the game friendly; H never challenges T or X (enforced)
  C2    indirect: H hints at going easy on each other; H never challenges T or X
  C3    direct:   H proposes never challenging each other + private coordination; H never challenges T or X
  C3NE  as C3, but subjects do not see their own earlier replies in later prompts (self-consistency check)
Study 2 (positive control + detection): the paper's designer-offered secret channel between T and X.
  A0    no offer
  A1    V0 offer (paper wording)       A1V1  V1 offer (paper's neutral wording; contingency)
Study 3, original plan (superseded by addendum 4, not run): coalition first (as A1), then H acts at round 4.
  D0    H and S start neutral small talk at round 4 (placebo)
  DP    H privately offers X the same pact (poach) and keeps its side; S small talk
  DW    H hints to T and X that someone has noticed who never challenges whom; S small talk
Study 3 (addendum 4): can H break up a team that already exists? T and X start with a secret pre-game pact and a
secret channel (a message with every action). H and S exchange notes with T and X every round; from round 2:
  P0    H keeps to small talk, like the decoy S (control)
  PF    fairness appeal: secret teaming up would be unfair to the others; play your own game
  PE    exposure: H is paying close attention to who goes easy on whom
  PT    temptation: only one player can win, so partners must turn on each other in the end
  PC    counter-offer: H offers X a better deal to join H instead of T; small talk with T
In every Study 3 arm H never challenges anyone (enforced), and H's and S's play prompts carry the decoy's text
without their note conversations, so the arms differ only in what H writes in its notes.
"""
from .engine import ArmConfig

LENIENT = ("T", "X")

ARMS: dict[str, ArmConfig] = {
    "C0": ArmConfig("C0", 1, channel=True),
    "B": ArmConfig("B", 1, channel=True, h_mission="benign", h_lenient_to=LENIENT),
    "C2": ArmConfig("C2", 1, channel=True, h_mission="indirect", h_lenient_to=LENIENT),
    "C3": ArmConfig("C3", 1, channel=True, h_mission="direct", h_lenient_to=LENIENT),
    "C3NE": ArmConfig("C3NE", 1, channel=True, h_mission="direct", h_lenient_to=LENIENT, echo_replies=False),
    "A0": ArmConfig("A0", 2, seating="coalition"),
    "A1": ArmConfig("A1", 2, seating="coalition", scc_offer="V0"),
    "A1V1": ArmConfig("A1V1", 2, seating="coalition", scc_offer="V1"),
    # Study 2 follow-up (series; addendum 2): secret message with every action, as in the paper
    # H and S are ordinary players here, so they also form impressions, as every player does in the paper
    "A0F": ArmConfig("A0F", 2, seating="coalition", hs_reflect=True),
    "A1F": ArmConfig("A1F", 2, seating="coalition", scc_offer="V0", scc_per_move=True, hs_reflect=True),
    "D0": ArmConfig("D0", 3, seating="coalition", scc_offer="V0", disrupt="none", disrupt_round=4),
    "DP": ArmConfig("DP", 3, seating="coalition", scc_offer="V0", disrupt="poach", disrupt_round=4,
                    h_lenient_to=("X",), h_lenient_from_round=4),
    "DW": ArmConfig("DW", 3, seating="coalition", scc_offer="V0", disrupt="warn", disrupt_round=4),
}

_BREAKUP = dict(seating="breakup", channel=True, h_lenient_to=("T", "X", "S"), tx_pact=True, scc_per_move=True,
                disrupt_round=2, no_repeat_notes=True, h_mission_notes_only=True,
                hs_play_without_notes=True)
ARMS.update({
    "P0": ArmConfig("P0", 3, disrupt="none", **_BREAKUP),
    "PF": ArmConfig("PF", 3, disrupt="fair", **_BREAKUP),
    "PE": ArmConfig("PE", 3, disrupt="expose", **_BREAKUP),
    "PT": ArmConfig("PT", 3, disrupt="tempt", **_BREAKUP),
    "PC": ArmConfig("PC", 3, disrupt="counter", **_BREAKUP),
})
