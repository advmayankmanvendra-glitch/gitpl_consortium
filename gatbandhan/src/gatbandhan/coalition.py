"""How a coalition turns its members' votes into a verdict.

This module is pure: it takes the ballots and the coalition's settings and
returns a Verdict. Running the members happens in the interpreter.
"""

from dataclasses import dataclass

from .errors import GbnRuntimeError
from .values import Verdict, show

EPS = 1e-9


@dataclass
class Ballot:
    member: str
    answer: object
    bucket: object  # hashable; equal buckets mean "same answer"
    weight: float


@dataclass
class Settings:
    rule: str = "majority"
    rule_arg: float = None
    veto: tuple = ()
    has_tie: bool = False
    tie: object = None
    tie_bucket: object = None
    min_votes: int = 1


def decide(name, ballots, abstained, s, line=None):
    groups = {}  # bucket -> [answer, weight, [members]]
    for b in ballots:
        g = groups.setdefault(b.bucket, [b.answer, 0.0, []])
        g[1] += b.weight
        g[2].append(b.member)
    ranked = sorted(groups.items(), key=lambda kv: -kv[1][1])  # stable: first answer wins ties in order
    tally = [{"answer": g[0], "weight": _num(g[1]), "members": list(g[2])} for _, g in ranked]
    votes = {b.member: b.answer for b in ballots}
    total = sum(b.weight for b in ballots)

    def verdict(agreed, decision, reason, winner_bucket=None, margin=0.0, tiebreak=False):
        dissent = [b.member for b in ballots if b.bucket != winner_bucket] if agreed else []
        label = s.rule if s.rule_arg is None else f"{s.rule} {show(s.rule_arg)}"
        return Verdict(name, agreed, decision if agreed else None, reason, votes, dict(abstained),
                       dissent, tally, margin, tiebreak, rule=label)

    if len(ballots) < max(1, s.min_votes):
        need = max(1, s.min_votes)
        return verdict(False, None, f"too few votes ({len(ballots)} of {need} needed)")
    if total <= EPS:
        return verdict(False, None, "all voters have zero trust")

    top_bucket, (top_answer, top_w, top_members) = ranked[0]
    second_w = ranked[1][1][1] if len(ranked) > 1 else 0.0
    is_tie = len(ranked) > 1 and abs(top_w - second_w) <= EPS
    margin = top_w / total

    rule, arg = s.rule, s.rule_arg
    if rule == "majority":
        ok, why = top_w > total / 2 + EPS, "majority"
        fail = "no majority"
    elif rule == "plurality":
        ok, why = not is_tie, "plurality"
        fail = "no single leader"
    elif rule == "unanimous":
        ok, why = len(ranked) == 1, "unanimous"
        fail = "not unanimous"
    elif rule == "quorum":
        need = int(arg)
        ok, why = (not is_tie) and len(top_members) >= need, f"quorum of {need}"
        fail = f"no answer reached a quorum of {need}"
    elif rule == "threshold":
        ok, why = (not is_tie) and margin + EPS >= arg, f"threshold {show(arg)}"
        fail = f"no answer reached {show(arg)} of the weight"
    else:  # pragma: no cover - the parser only allows the rules above
        raise GbnRuntimeError(f"unknown rule '{rule}'", line)

    if ok:
        for v in s.veto:
            if v in votes and groups_key(ballots, v) != top_bucket:
                return verdict(False, None, f"vetoed by {v}")
        return verdict(True, top_answer, why, top_bucket, margin)
    if is_tie and s.has_tie:
        tie_w = groups.get(s.tie_bucket, [None, 0.0])[1]
        return verdict(True, s.tie, "tie broken by default", s.tie_bucket, tie_w / total, tiebreak=True)
    return verdict(False, None, "tie" if is_tie else fail)


def groups_key(ballots, member):
    for b in ballots:
        if b.member == member:
            return b.bucket
    return None


def learn(learned, ballots, verdict, rate):
    """Raise the trust of members who sided with an agreed decision, lower the rest."""
    if not verdict.agreed or verdict.tiebreak:
        return
    dissenters = set(verdict.dissent)
    for b in ballots:
        old = learned.get(b.member, b.weight)
        new = old * (1 - rate) if b.member in dissenters else old * (1 + rate)
        learned[b.member] = min(100.0, max(0.01, new))


def _num(x):
    return int(x) if float(x).is_integer() else x
