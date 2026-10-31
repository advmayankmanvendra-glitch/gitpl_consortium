"""Syntax tree nodes. Every node carries the source line it started on."""

from dataclasses import dataclass, field


@dataclass
class Node:
    line: int


# ---- expressions ----

@dataclass
class Literal(Node):
    value: object


@dataclass
class Template(Node):
    parts: list  # str or expression nodes


@dataclass
class Name(Node):
    name: str


@dataclass
class ListLit(Node):
    items: list


@dataclass
class MapLit(Node):
    entries: list  # (key str, expr)


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Call(Node):
    callee: Node
    args: list


@dataclass
class Index(Node):
    target: Node
    index: Node


@dataclass
class Field(Node):
    target: Node
    name: str


@dataclass
class FnLit(Node):
    params: list
    body: list


# ---- statements ----

@dataclass
class Let(Node):
    name: str
    value: Node


@dataclass
class Assign(Node):
    target: Node
    value: Node


@dataclass
class ExprStmt(Node):
    expr: Node


@dataclass
class FnDecl(Node):
    name: str
    params: list
    body: list


@dataclass
class MemberDecl(Node):
    name: str
    params: list
    trust: Node  # or None
    body: list


@dataclass
class Rule(Node):
    kind: str  # majority plurality unanimous quorum threshold
    arg: Node = None


@dataclass
class CoalitionDecl(Node):
    name: str
    params: list
    members: list  # expressions
    rule: Rule
    veto: list = field(default_factory=list)
    tie: Node = None
    key: Node = None
    learn: Node = None
    weights: Node = None
    min_votes: Node = None


@dataclass
class Return(Node):
    value: Node
    feeling: Node = None


@dataclass
class VowDef(Node):
    name: str
    value: Node


@dataclass
class BondDecl(Node):
    name: str
    human: Node
    ai: Node
    keep: Node = None
    key: Node = None
    vows: list = field(default_factory=list)  # VowDef


@dataclass
class VowStmt(Node):
    bond: str
    vow: VowDef


@dataclass
class Remember(Node):
    bond: str
    text: Node
    by: str = None       # "human", "ai" or None for both
    feeling: Node = None
    amends: Node = None  # entry number, for amend


@dataclass
class Abstain(Node):
    reason: Node


@dataclass
class If(Node):
    cond: Node
    then: list
    otherwise: list  # or None


@dataclass
class While(Node):
    cond: Node
    body: list


@dataclass
class For(Node):
    var: str
    iterable: Node
    body: list


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class Match(Node):
    subject: Node
    agreed_name: str
    agreed_body: list  # or None
    split_name: str
    split_body: list  # or None
