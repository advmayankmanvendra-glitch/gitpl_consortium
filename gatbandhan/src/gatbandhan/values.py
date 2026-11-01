"""Runtime values that are not plain Python values.

Gatbandhan numbers, strings, booleans, none, lists and maps are Python's
int/float, str, bool, None, list and dict. Functions, members, coalitions and
verdicts are the classes below.
"""

from dataclasses import dataclass, field


class Callable:
    """Anything that can be called."""


@dataclass(eq=False)
class Function(Callable):
    name: str
    params: list
    body: list
    closure: object


@dataclass(eq=False)
class Builtin(Callable):
    name: str
    fn: object
    pass_interp: bool = False


@dataclass(eq=False)
class Member(Callable):
    """A function whose answer is one vote. It may ``abstain``."""
    name: str
    params: list
    body: list
    closure: object
    trust: float = 1.0


@dataclass(eq=False)
class Coalition(Callable):
    name: str
    decl: object
    closure: object
    learned: dict = field(default_factory=dict)  # member name -> trust
    history: list = field(default_factory=list)


@dataclass(eq=False)
class Verdict:
    coalition: str
    agreed: bool
    decision: object
    reason: str
    votes: dict        # member name -> answer
    abstained: dict    # member name -> reason
    dissent: list      # member names that voted for something else
    tally: list        # [{answer, weight, members}] strongest first
    margin: float      # winning weight / total voting weight
    tiebreak: bool = False
    feelings: dict = field(default_factory=dict)  # member name -> feeling
    question: object = None
    rule: str = ""
    partners: tuple = ()   # for a bond: (human name, ai name)
    proposal: object = None  # the Proposal decided on, if one was asked
    outcome: str = ""      # for a bond: approved, rejected, disagreed or silent
    marks: dict = field(default_factory=dict)  # for a bond: partner -> 1, 0 or None (silent)

    FIELDS = ("agreed", "decision", "reason", "votes", "abstained", "dissent",
              "tally", "margin", "tiebreak", "coalition", "feelings", "question",
              "bits", "signal", "gate", "rule", "outcome", "approved", "proposal")

    @property
    def approved(self):
        """True only for a real yes: a bond's approval, or a coalition's agreement."""
        return self.outcome == "approved" if self.partners else self.agreed

    def get(self, name):
        if name not in self.FIELDS:
            return None
        if name == "bits":
            return self.bits()
        if name == "gate":
            return self.gate()
        if name == "outcome":
            return self.outcome or ("agreed" if self.agreed else "split")
        if name == "signal":
            row = list(self.bits().values())
            if not row or None in row:
                return None
            return Bits(int("".join(map(str, row)), 2), len(row))
        return getattr(self, name)

    def bits(self):
        """Each voice as a bit.

        For a bond both partners are listed: 1 for yes, 0 for no, and none for a
        partner who stayed silent, because silence is neither yes nor no.
        For a coalition only voters are listed: 1 if they stand with the
        decision (or the leading answer).
        """
        if self.partners:
            return dict(self.marks)
        if self.agreed:
            lead = {m for m in self.votes if m not in self.dissent}
        else:
            lead = set(self.tally[0]["members"]) if self.tally else set()
        names = list(self.partners) if self.partners else list(self.votes)
        return {n: 1 if n in lead else 0 for n in names}

    def gate(self):
        """The decision written as a logic gate, e.g. ``1 ∧ 1 = 1`` for a bond."""
        bits = list(self.bits().values())
        out = 1 if self.agreed else 0
        if self.partners:
            mark = lambda b: "?" if b is None else str(b)
            out = "?" if self.outcome == "silent" else (1 if self.outcome == "approved" else 0)
            return f"{mark(bits[0])} ∧ {mark(bits[1])} = {out}"
        return f"{self.rule.upper()}({', '.join(map(str, bits))}) = {out}"


@dataclass(frozen=True)
class Bits:
    """A fixed-width row of 0s and 1s, like ``0b0101``. Bit 0 is the leftmost."""
    value: int
    width: int

    def __post_init__(self):
        if self.width < 1:
            raise ValueError("bits need a width of at least 1")
        if not 0 <= self.value < (1 << self.width):
            raise ValueError(f"{self.value} does not fit in {self.width} bits")

    @property
    def mask(self):
        return (1 << self.width) - 1

    def digits(self):
        return format(self.value, "b").zfill(self.width)

    def __getitem__(self, i):
        return int(self.digits()[i])

    def __len__(self):
        return self.width

    def __iter__(self):
        return (int(c) for c in self.digits())


class Sealed:
    """Marker for containers that belong to a bond and can never be changed."""


def _refuse(self, *a, **k):
    raise SealedError(self)


class SealedError(Exception):
    def __init__(self, container):
        self.container = container


class SealedList(Sealed, list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = sort = reverse = _refuse
    __iadd__ = __imul__ = _refuse


class SealedMap(Sealed, dict):
    __setitem__ = __delitem__ = pop = popitem = clear = update = setdefault = _refuse


def seal(v, owner=None):
    """Deep-copy a value into containers that refuse every change.

    ``owner`` is the name of the bond the value belongs to, so a refused change
    can be written into that bond's memory.
    """
    if isinstance(v, list):
        out = SealedList(seal(x, owner) for x in v)
    elif isinstance(v, dict):
        out = SealedMap((k, seal(x, owner)) for k, x in v.items())
    else:
        return v
    out.owner = owner
    return out


def unseal(v):
    """A plain, changeable deep copy (used for JSON and for copies handed out)."""
    if isinstance(v, list):
        return [unseal(x) for x in v]
    if isinstance(v, dict):
        return {k: unseal(x) for k, x in v.items()}
    return v


@dataclass(eq=False)
class Bond:
    """A bond between one human and one AI. Its vows and memory only grow."""
    name: str
    human_name: str
    ai: object          # a Member, a Function, or a model name
    ai_name: str
    key: object = None
    vows: dict = field(default_factory=dict)      # name -> sealed value
    vow_lines: dict = field(default_factory=dict)
    journal: object = None                         # journal.Journal

    FIELDS = ("name", "human", "ai", "vows", "memory", "seal")

    def get(self, name):
        if name == "name":
            return self.name
        if name == "human":
            return self.human_name
        if name == "ai":
            return self.ai_name
        if name == "vows":
            return seal(self.vows, self.name)
        if name == "memory":
            return seal(self.journal.public_entries(), self.name)
        if name == "seal":
            return self.journal.head
        return None


class Proposal:
    """A proposal the bond decides on. Its fingerprint never changes; a revision is a new proposal.

    Its status is read from the bond's memory each time, so it survives between runs:
    pending (not decided yet, or only met with silence), disagreed, approved, rejected,
    or replaced (a newer version exists).
    """
    FIELDS = ("id", "version", "text", "fingerprint", "replaces", "status", "rounds", "bond")

    def __init__(self, bond, entry):
        self.bond = bond
        self.id = entry["n"]
        self.version = entry["version"]
        self.text = entry["text"]
        self.fingerprint = entry["fingerprint"]
        self.replaces = entry.get("replaces")

    def __deepcopy__(self, memo):
        return self   # a proposal cannot change, so copies may share it

    def rounds(self):
        return [e for e in self.bond.journal.entries
                if e["kind"] == "decision" and e.get("proposal") == self.fingerprint]

    def status(self):
        outcomes = [e.get("outcome") for e in self.rounds()]
        for final in ("approved", "rejected"):
            if final in outcomes:
                return final
        if any(e["kind"] == "proposal" and e.get("replaces") == self.id for e in self.bond.journal.entries):
            return "replaced"
        return "disagreed" if outcomes and outcomes[-1] == "disagreed" else "pending"

    def get(self, name):
        if name == "status":
            return self.status()
        if name == "rounds":
            return len(self.rounds())
        if name == "bond":
            return self.bond.name
        return getattr(self, name)


def type_name(v):
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "map"
    if isinstance(v, Member):
        return "member"
    if isinstance(v, Coalition):
        return "coalition"
    if isinstance(v, Bond):
        return "bond"
    if isinstance(v, Verdict):
        return "verdict"
    if isinstance(v, Proposal):
        return "proposal"
    if isinstance(v, Bits):
        return "bits"
    if isinstance(v, Callable):
        return "fn"
    return type(v).__name__


def show(v, quote=False):
    """The text form of a value, as print and string interpolation use it."""
    if v is None:
        return "none"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(round(v, 10))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' if quote else v
    if isinstance(v, Bits):
        return "0b" + v.digits()
    if isinstance(v, list):
        return "[" + ", ".join(show(x, True) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_key(k)}: {show(x, True)}" for k, x in v.items()) + "}"
    if isinstance(v, Proposal):
        return f"<proposal {v.id} v{v.version} {v.status()}: {show(v.text, True)}>"
    if isinstance(v, Verdict):
        if v.outcome in ("approved", "rejected"):
            return f"<verdict {v.coalition}: {v.outcome} {show(v.decision, True)} ({v.reason})>"
        if v.outcome:
            return f"<verdict {v.coalition}: {v.outcome} ({v.reason})>"
        if v.agreed:
            return f"<verdict {v.coalition}: agreed {show(v.decision, True)} ({v.reason}, margin {show(round(v.margin, 2))})>"
        return f"<verdict {v.coalition}: split ({v.reason})>"
    if isinstance(v, Member):
        return f"<member {v.name}>"
    if isinstance(v, Coalition):
        return f"<coalition {v.name}>"
    if isinstance(v, Bond):
        return f"<bond {v.name}: {v.human_name} and {v.ai_name}>"
    if isinstance(v, Callable):
        return f"<fn {v.name}>"
    return str(v)


def _key(k):
    if isinstance(k, str) and k.isidentifier():
        return k
    return show(k, True)


def freeze(v):
    """A hashable stand-in for a value, so equal answers land in one bucket."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return (type(v).__name__, v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if isinstance(v, Bits):
        return ("bits", v.value, v.width)
    if isinstance(v, list):
        return ("list", tuple(freeze(x) for x in v))
    if isinstance(v, dict):
        return ("map", tuple(sorted((str(k), freeze(x)) for k, x in v.items())))
    if isinstance(v, Proposal):
        return ("proposal", v.fingerprint)
    return ("id", id(v))
