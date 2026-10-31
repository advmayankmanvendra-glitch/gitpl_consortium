# Gatbandhan language specification, version 0.1

Gatbandhan (गठबंधन, "alliance" or "bond") is a small language whose central idea is a
**bond** between one human and one AI. Decisions in a bond need both partners, its vows
cannot be overwritten, and its memory only grows. Underneath, a bond is the smallest
**coalition**: a group of independent members whose answers are combined by a rule.

Files use the extension `.gbn` and are UTF-8 text.

## 1. Principles

1. **Neither partner decides alone.** A bond's decision stands only when the human and
   the AI give the same answer.
2. **Silence is not consent.** A partner who does not answer blocks the decision.
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
- Numbers: `42`, `3.14`, `1_000`, and binary `0b1011` (= 11).
- Strings: `"..."` with escapes `\n \t \" \\ \{ \}`. `{expr}` inside a string
  interpolates the value of `expr`. An interpolated expression cannot contain string
  literals.
- Keywords: `let fn member coalition bond vow remember amend with by return abstain if
  else while for in break continue match true false none and or not`.
- Contextual words, which are ordinary names elsewhere: `trust` (after a member's
  parameters), `feeling` (after `with`), `agreed` and `split` (in `match`), `human` and
  `ai` (in a bond and after `by`), and coalition and bond field names.

## 3. Values

| Type | Examples | Notes |
| --- | --- | --- |
| `num` | `1`, `2.5` | `7 / 2` is `3.5`; `6 / 3` is `2` |
| `str` | `"hi {name}"` | |
| `bool` | `true`, `false` | never equal to a number |
| `none` | `none` | |
| `list` | `[1, 2]` | |
| `map` | `{a: 1, "b c": 2}` | `m.a` and `m["a"]`; a missing key is `none` |
| `fn` | `fn(x) { return x }` | closures |
| `member` | `member m(x) { ... }` | a function whose answer is a vote |
| `coalition` | `coalition c(x) { ... }` | calling it returns a verdict |
| `bond` | `bond us { ... }` | calling it returns a verdict |
| `verdict` | | the outcome of a coalition or bond |

Falsy values: `false`, `none`, `0`, `""`, `[]`, `{}`. Everything else is truthy.
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
`x.f`. The bit operators `& | ^ ~ << >>` work on whole numbers. Because they bind
tighter than comparisons, `a & b == 0` means `(a & b) == 0`.

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
  human: "Mayank"            # the human partner's name
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

The verdict agrees ("both agree") only when both answered the same. Otherwise it splits
with "the partners disagree" or "no consent: X did not answer". Every decision is written
to the bond's memory with the question, both votes and both feelings.

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
`bits(us.seal)` shows it as 256 zeros and ones. `memory(us)` and
`us.memory` are sealed; `copy(...)` gives a changeable copy.

### 7.4 What is refused

All of these raise a **bond error**, which no code can catch. Before stopping, the attempt
is written into the bond's memory as a `refused` entry.

- assigning, `let`-binding, shadowing, or using as a parameter or loop variable the bond's
  name, in any scope;
- declaring the bond a second time, or a function, member or coalition with its name;
- setting any field of the bond (`us.human = ...`);
- changing a vow, or anything inside a vow's value;
- changing the memory or anything inside it.

### 7.5 Kept bonds

With `keep: "file"` (relative to the program's directory), memory is a JSON-lines file.
Each entry holds the SHA-256 hash of the previous entry plus its own content, so:

- the next run continues the same bond, with its vows and memory;
- a program that names different partners for the file is refused;
- a vow made in an earlier run cannot be changed by a later program;
- a file whose entries were edited, removed or reordered is refused on open.

The file belongs to its owner, who can still delete it. Gatbandhan makes tampering
evident, not impossible.

## 8. Verdicts

| Field | Meaning |
| --- | --- |
| `agreed` | whether a decision was reached |
| `decision` | the decided answer, or `none` |
| `reason` | why, for example `majority`, `vetoed by m`, `both agree` |
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
| `gate` | the decision written as a logic gate, for example `1 ∧ 1 = 1` |

**Bits and gates.** Every decision is also a small circuit. A voice's bit is 1 when it
stands with the decision, or with the leading answer when there is none, and 0 otherwise.
A bond lists both partners, and a partner who did not answer is 0, so a bond's gate is
an AND gate: `1 ∧ 1 = 1` is consent, `1 ∧ 0 = 0` is disagreement, `0 ∧ 1 = 0` is
silence. A coalition's gate is named after its rule, for example `MAJORITY(1, 1, 0) = 1`.

```gbn
match verdict {
  agreed d  { ... }    # d is the decision
  split why { ... }    # why is the reason
}
```

Either arm may be left out, and the names after `agreed` and `split` are optional.

## 9. Built-in functions

`print(...)`, `len`, `str`, `num`, `type_of`, `lower`, `upper`, `trim`, `contains`,
`starts_with`, `ends_with`, `split(s, sep?)`, `join(list, sep?)`, `replace`, `keys`,
`values`, `push`, `range(n)` / `range(a, b)`, `round(x, digits?)`, `abs`, `min`, `max`,
`sum`, `sort`, `copy`, `bits(n, width?)` (a whole number as a string of 0s and 1s, or a
bond's seal as 256 bits), `error(msg)`, `version()`.

Partners and models: `hear(prompt)` reads a line from the human (or `none`);
`script_human(list)`; `consult(model, text)` asks a model; `script(model, replies)` makes
an offline model that gives the replies in order. A model whose name starts with
`claude` is called through the Anthropic Messages API when `ANTHROPIC_API_KEY` is set.

Bonds and coalitions: `vows(bond)`, `memory(bond)`, `trust(coalition)`,
`history(coalition)`.

## 10. Errors

Syntax and runtime errors report the line. Runtime errors inside a member become
abstentions; elsewhere they stop the program. Bond errors always stop the program.
