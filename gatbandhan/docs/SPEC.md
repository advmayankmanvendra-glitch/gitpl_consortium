# Gatbandhan language specification, version 0.1

Gatbandhan (गठबंधन, "alliance" or "bond") is a small language whose central idea is a
**bond** between one human and one AI. Decisions in a bond need both partners, its vows
cannot be overwritten, and its memory only grows. Underneath, a bond is the smallest
**coalition**: a group of independent members whose answers are combined by a rule.

Files use the extension `.gbn` and are UTF-8 text.

## 1. Principles

1. **Neither partner decides alone.** A bond's decision stands only when the human and
   the AI give the same answer.
2. **Silence is not consent, and it is not refusal either.** A partner who does not
   answer blocks the decision, and the silence is recorded as its own state.
3. **What is promised stays promised.** A vow, once made, can never take another value.
4. **History is never rewritten.** Memory can be added to and amended, never changed or
   erased, and every refused attempt is itself remembered.
5. **Feelings travel with answers.** An answer may carry a feeling, which is kept with
   the decision.
6. **Independent voices.** Members of a coalition cannot see or change each other's
   inputs, and one member's failure is an abstention, not a crash.

## 2. Lexical structure

- Comments start with `#` and run to the end of the line.
- Newlines are not significant; statements may optionally be separated by `;`.
- Numbers: `42`, `3.14`, `1_000`.
- Bits: `0b0101`, `0b1_0000` (a `bits` value; the number of digits is its width).
- Strings: `"..."` with escapes `\n \t \" \\ \{ \}`. `{expr}` inside a string
  interpolates the value of `expr`. An interpolated expression cannot contain string
  literals.
- Keywords: `let fn member coalition bond vow remember amend with by return abstain if
  else while for in break continue match true false none and or not`.
- Contextual words, which are ordinary names elsewhere: `trust` (after a member's
  parameters), `feeling` (after `with`), `approved`, `rejected`, `disagreed`, `silent`, `agreed` and `split` (in `match`), `human` and
  `ai` (in a bond and after `by`), and coalition and bond field names.

## 3. Values

| Type | Examples | Notes |
| --- | --- | --- |
| `num` | `1`, `2.5` | `7 / 2` is `3.5`; `6 / 3` is `2` |
| `str` | `"hi {name}"` | |
| `bits` | `0b0101` | fixed-width row of 0s and 1s (section 4.1) |
| `bool` | `true`, `false` | never equal to a number |
| `none` | `none` | |
| `list` | `[1, 2]` | |
| `map` | `{a: 1, "b c": 2}` | `m.a` and `m["a"]`; a missing key is `none` |
| `fn` | `fn(x) { return x }` | closures |
| `member` | `member m(x) { ... }` | a function whose answer is a vote |
| `coalition` | `coalition c(x) { ... }` | calling it returns a verdict |
| `bond` | `bond us { ... }` | calling it returns a verdict |
| `verdict` | | the outcome of a coalition or bond |
| `proposal` | `propose(us, "text")` | something a bond decides on, with its own fingerprint (section 7.6) |

Falsy values: `false`, `none`, `0`, bits that are all 0, `""`, `[]`, `{}`. Everything else is truthy.
`==` compares by value (lists and maps deeply).

## 4. Statements and expressions

```gbn
let x = 1                 # new binding in the current scope
x = x + 1                 # assign an existing binding
xs[0] = 5  m.key = 6      # set an index or field
fn name(a, b) { return a + b }
if c { } else if d { } else { }
while c { }
for x in [1, 2] { }       # lists, strings (characters), maps (keys)
break  continue
```

Operators, loosest to tightest: `or`; `and`; `not`; `== != < <= > >= in`; `|`; `^`;
`&`; `<< >>`; `+ -`; `* / %`; unary `-` and `~`; calls `f(x)`, indexing `x[i]`, fields
`x.f`. Because the bit operators bind tighter than comparisons, `a & b == 0` means
`(a & b) == 0`.

### 4.1 Bits

Bits are a type of their own, not another spelling of numbers. `0b0101` has width 4 and
prints as `0b0101`; `0b01` and `0b1` are different values (widths 2 and 1).

| Expression | Result |
| --- | --- |
| `a & b`, `a \| b`, `a ^ b` | bitwise AND, OR, XOR; the result has the larger width |
| `~a` | every bit flipped, same width |
| `a << n`, `a >> n` | shifted by `n` places, same width; bits pushed out are lost |
| `a + b` | `a` and `b` joined side by side: `0b01 + 0b1 == 0b011` |
| `len(a)`, `a[i]`, `for x in a` | width, bit `i` from the left (0 or 1), each bit in turn |
| `num(a)` | the bits read as a whole number |
| `bits(x, width?)` | bits from a whole number, a list of 0s and 1s, a string like `"0110"`, or a bond's seal |

Mixing bits and numbers in a bit operator is an error: write `bits(n, width)` to turn a
number into bits. The operators `& | ^ ~ << >>` also work on two whole numbers, giving a
number.

## 5. Members

```gbn
member name(params) trust 2 {
  ...
  return answer with feeling "glad"
  abstain "reason"
}
```

A member is a function whose answer is a vote. `trust` (default `1`) is its voting
weight. `abstain` ends the member without voting. Returning `none`, or raising an error,
also counts as abstaining. The optional `with feeling` attaches a feeling to the answer.
Calling a member directly returns its answer, or `none` if it abstains.

## 6. Coalitions

```gbn
coalition name(params) {
  members: m1, m2, fn(x) { return ... }, other_coalition
  rule: majority            # default
  veto: m2                  # optional, one or more members
  tie: "fallback"           # optional
  key: fn(answer) { ... }   # optional: answers with equal keys count as the same
  weights: {m1: 0.5}        # optional: overrides members' trust
  learn: 0.2                # optional: adapt trust after each agreed decision
  min_votes: 2              # optional, default 1
}
```

Field values are evaluated on each call, with the parameters in scope.

**Running.** Each member is called with its own deep copy of the arguments. A member
that abstains, returns `none` or raises an error does not vote; the reason is recorded in
`abstained`. A coalition or bond used as a member votes its decision when it agrees and
abstains when it splits. Attempts to overwrite a bond are never turned into abstentions:
they stop the program (section 7.4).

**Counting.** Votes are grouped by answer (or by `key(answer)`). Each group's weight is
the sum of its voters' weights. A voter's weight is its learned trust if the coalition has
learned one, else its entry in `weights`, else its `trust`.

**Rules.** With `W` the total voting weight and `top` the heaviest group:

| Rule | Agreed when |
| --- | --- |
| `majority` | `top` has more than half of `W` |
| `plurality` | `top` is strictly heavier than every other group |
| `unanimous` | every voter gave the same answer |
| `quorum N` | `top` is strictly heaviest and has at least `N` voters |
| `threshold X` | `top` is strictly heaviest and has at least `X` (0 to 1) of `W` |

Then, in order: fewer than `min_votes` voters means a split ("too few votes"). If the rule
agreed but a `veto` member voted for a different answer, the verdict splits ("vetoed by
m"). If the rule failed because the two heaviest groups weigh the same and a `tie` is
given, the verdict agrees on the tie value with `tiebreak` set.

**Learning.** With `learn: r`, after each agreed verdict (not tie-breaks) every voter's
trust is multiplied by `1 + r` if it voted with the decision and by `1 - r` if it
dissented, kept between 0.01 and 100. `trust(c)` returns the learned trust and
`history(c)` every verdict so far.

## 7. Bonds

```gbn
bond us {
  human: "Asha"            # the human partner's name
  ai: saathi                 # a member, a function, or a model name
  keep: "us.journal"         # optional: a file that keeps the memory between runs
  key: fn(a) { ... }         # optional: how answers are compared
  vow honesty: "We tell each other the truth."
  vow consent: "Neither of us decides alone."
}
```

### 7.1 Deciding together

`us(question)` asks both partners the same question and returns a verdict.

- The **human** answers at the terminal (answer, then an optional feeling), or from
  `script_human([...])`, whose entries are strings or `{answer, feeling}` maps. An empty
  line or end of input means no answer.
- The **AI** is called with the question if it is a member or function. If it is a model
  name, the model is consulted with a system message naming the bond, the partners and
  the vows, and asked for `{"answer": ..., "feeling": ...}` JSON.
- Text answers are compared trimmed and case-insensitively unless `key` is given.
- Without a `key`, words that mean yes are the same answer, and so are words that mean
  no, in English or Hindi: yes, y, yeah, yep, haan, haa, ha, ji, ok, okay, sure, agree,
  agreed, approve, approved, true; and no, n, nope, nahi, nahin, na, disagree, reject,
  rejected, never, false. A final `.` or `!` is ignored.

Every question ends in exactly one of four **outcomes**, kept in `outcome`:

| Outcome | When | `agreed` | `approved` | Gate | Reason |
| --- | --- | --- | --- | --- | --- |
| `approved` | both gave the same answer, and it is not a no | true | true | `1 ∧ 1 = 1` | `both approve` |
| `rejected` | both said no | true | false | `0 ∧ 0 = 0` | `rejected together` |
| `disagreed` | both answered, differently | false | false | `1 ∧ 0 = 0` or `0 ∧ 1 = 0` | `the partners disagree` |
| `silent` | at least one partner did not answer | false | false | `? ∧ 1 = ?` and so on | `no consent: X did not answer` |

Only `approved` is a commitment. A mutual rejection is agreement that the answer is no:
the partners' answers match, but nothing was approved. Silence is not a 0: a silent
partner's bit is `none` (shown as `?` in the gate), and the gate's result is unknown.
Every decision is written to the bond's memory with its outcome, the question, both
votes and both feelings.

### 7.2 Vows

Vows are made in the bond or later with `vow us.name = value`. Making the same vow again
with an equal value does nothing. Making it with a different value is refused. Vows are
read with `us.vows.name` or `vows(us)`, and the values are sealed: lists and maps inside
them cannot be changed.

### 7.3 Memory

```gbn
remember us "text" by human with feeling "grateful"   # by human | by ai | (both)
amend us 4 "a corrected version of entry 4"
for e in memory(us) { print(e.n, e.kind, e.by, e.text, e.feeling) }
```

Entries are maps with `n`, `kind` (`bond`, `vow`, `decision`, `memory`, `amend`,
`refused`), `by`, `text`, `at`, and kind-specific fields (`question`, `votes`,
`feelings`, `agreed`, `decision`, `gate`, `vow`, `value`, `amends`).

**The seal.** `us.seal` is the bond's 256-bit fingerprint, written as 64 hex digits: the
SHA-256 hash of the newest memory entry, which itself covers every entry before it. Each
new entry changes the seal, and changing a single bit of past memory would too.
`bits(us.seal)` gives it as a 256-bit `bits` value. `memory(us)` and
`us.memory` are sealed; `copy(...)` gives a changeable copy.

### 7.4 What is refused

All of these raise a **bond error**, which no code can catch. Before stopping, the attempt
is written into the bond's memory as a `refused` entry.

- assigning, `let`-binding, shadowing, or using as a parameter or loop variable the bond's
  name, in any scope;
- declaring the bond a second time, or a function, member or coalition with its name;
- setting any field of the bond (`us.human = ...`);
- changing a vow, or anything inside a vow's value;
- changing the memory or anything inside it;
- asking a proposal that is already approved, rejected or replaced (section 7.6).

### 7.5 Kept bonds

With `keep: "file"` (relative to the program's directory), memory is a JSON-lines file.
Each entry holds the SHA-256 hash of the previous entry plus its own content, so:

- the next run continues the same bond, with its vows and memory;
- a program that names different partners for the file is refused;
- a vow made in an earlier run cannot be changed by a later program;
- a file whose entries were edited, removed or reordered is refused on open.

The file belongs to its owner, who can still delete it. Gatbandhan makes tampering
evident, not impossible.

### 7.6 Proposals

A plain question is decided once, on the spot. A **proposal** is something the bond
decides on that has its own identity, can wait, and can be revised.

```gbn
let p = propose(us, "Ship version 2")       # written into memory, status "pending"
let v = us(p)                                # both partners answer this exact proposal
let p2 = revise(p, "Ship version 2 after the tests pass")   # version 2, a new proposal
for q in proposals(us) { print(q) }          # every proposal, also from earlier runs
```

- `propose(bond, text)` writes a `proposal` entry and returns the proposal. Its
  **fingerprint** is the SHA-256 of `{bond, n, text, version, replaces}` written as
  canonical JSON (sorted keys, no spaces), where `n` is its entry number.
- Asking the bond a proposal, `us(p)`, works like a question, and the `decision` entry
  records the proposal's fingerprint (`proposal`) and number (`proposal_id`). An answer
  always belongs to one fingerprint, so it can never count for a different text.
- `revise(p, text)` makes a new proposal with `version` one higher and `replaces` set to
  the old one's number. Approvals of the old version do not carry over. Only the newest
  version can be revised.
- `proposals(bond)` lists every proposal in the bond's memory, so with `keep:` a proposal
  made in one run can be answered in a later one.

A proposal's fields are `id`, `version`, `text`, `fingerprint`, `replaces`, `bond`,
`rounds` (how many times it was asked) and `status`, which is read from memory each time:

| Status | Meaning |
| --- | --- |
| `pending` | not decided yet: never asked, or only met with silence |
| `disagreed` | the last time it was asked, the partners answered differently; it can be asked again |
| `approved` | both said yes; final |
| `rejected` | both said no; final |
| `replaced` | a newer version exists; final |

Asking a proposal that is `approved`, `rejected` or `replaced` is refused like an
overwrite: a decided proposal stays decided, and an old version is never reused.
Silence and disagreement never close a proposal, so it can wait as long as needed.

## 8. Verdicts

| Field | Meaning |
| --- | --- |
| `outcome` | for a bond: `approved`, `rejected`, `disagreed` or `silent`; for a coalition: `agreed` or `split` |
| `approved` | for a bond, true only when both said yes to the same thing; for a coalition, the same as `agreed` |
| `proposal` | for a bond asked a proposal, that proposal; otherwise `none` |
| `agreed` | whether a decision was reached (for a bond: whether the answers match, so a mutual rejection is agreed but not approved) |
| `decision` | the decided answer, or `none` |
| `reason` | why, for example `majority`, `vetoed by m`, `both approve` |
| `votes` | map of voter name to answer |
| `abstained` | map of member name to the reason it did not vote |
| `dissent` | voters whose answer differs from the decision |
| `tally` | list of `{answer, weight, members}`, heaviest first |
| `margin` | the decision's share of the voting weight |
| `tiebreak` | whether the decision came from `tie` |
| `feelings` | map of voter name to feeling |
| `question` | for a bond, the question asked |
| `rule` | the rule used, for example `majority` or `threshold 0.7`; `and` for a bond |
| `bits` | map of each voice to a bit (see below) |
| `signal` | the same bits as a `bits` value, for example `0b11` for a bond's consent; `none` when a partner was silent |
| `gate` | the decision written as a logic gate, for example `1 ∧ 1 = 1` |

**Bits and gates.** Every decision is also a small circuit. A voice's bit is 1 when it
stands with the decision, or with the leading answer when there is none, and 0 otherwise.
A bond lists both partners with three possible marks: 1 for yes (or for an answer that
leads), 0 for no (or for an answer that differs), and `none` for silence. A bond's gate
is an AND gate: `1 ∧ 1 = 1` is consent, `0 ∧ 0 = 0` is a mutual rejection, `1 ∧ 0 = 0`
is disagreement, and `1 ∧ ? = ?` is silence. The gate alone does not tell rejection
from disagreement, so read `outcome` too. A coalition's gate is named after its rule,
for example `MAJORITY(1, 1, 0) = 1`.

```gbn
match verdict {
  approved d      { ... }    # a bond: both said yes; d is the decision
  rejected why    { ... }    # a bond: both said no
  disagreed why   { ... }    # a bond: the partners answered differently
  silent why      { ... }    # a bond: someone did not answer
  agreed d        { ... }    # any verdict whose answers match (approved or rejected)
  split why       { ... }    # any verdict with no decision (disagreed or silent)
}
```

The most specific arm wins: for a bond, the arm named after its outcome runs if there
is one, otherwise `agreed` or `split`. A coalition only uses `agreed` and `split`.
Every arm may be left out, and the names after the arm words are optional. The name is
the decision after `approved` and `agreed`, and the reason after the others. Code that
acts on a commitment should use `approved`, because `agreed` also covers a mutual no.

## 9. Built-in functions

`print(...)`, `len`, `str`, `num`, `type_of`, `lower`, `upper`, `trim`, `contains`,
`starts_with`, `ends_with`, `split(s, sep?)`, `join(list, sep?)`, `replace`, `keys`,
`values`, `push`, `range(n)` / `range(a, b)`, `round(x, digits?)`, `abs`, `min`, `max`,
`sum`, `sort`, `copy`, `bits(x, width?)` (section 4.1), `error(msg)`, `version()`.

Partners and models: `hear(prompt)` reads a line from the human (or `none`);
`script_human(list)`; `consult(model, text)` asks a model; `script(model, replies)` makes
an offline model that gives the replies in order. A model whose name starts with
`claude` is called through the Anthropic Messages API when `ANTHROPIC_API_KEY` is set.

Bonds and coalitions: `vows(bond)`, `memory(bond)`, `propose(bond, text)`,
`revise(proposal, text)`, `proposals(bond)` (section 7.6), `trust(coalition)`,
`history(coalition)`.

## 10. Errors

Syntax and runtime errors report the line. Runtime errors inside a member become
abstentions; elsewhere they stop the program. Bond errors always stop the program.
