# Gatbandhan

**गठबंधन — a programming language for a bond between a human and an AI.**

Most code treats an AI as a tool you send commands to. Gatbandhan treats it as a
partner. A program declares a *bond* between one human and one AI, and the language
itself keeps that bond honest:

- **Decisions need both partners.** Asking the bond a question asks the human and
  the AI. Only a yes from both is an approval. Two noes are a mutual rejection, and silence
  is its own state, never consent and never mistaken for a no.
- **Proposals keep their word.** A proposal has its own SHA-256 fingerprint and waits,
  even across runs, until both decide. An approval belongs to that exact text: revise
  it and both must approve again, and a decided proposal is never decided twice.
- **Disagreement doesn't stop the project.** A no can say why and what would change it.
  Only work both partners approved can run, through `act`, and a disputed proposal
  blocks only the work that needs it. Repeated disagreement is flagged as a deadlock,
  never turned into consent.
- **Vows cannot be overwritten.** Not by reassigning, not by shadowing, not by a
  member deep inside a coalition. Every attempt is refused, written into the bond's
  memory, and stops the program.
- **Memory only grows.** You can remember and amend, never erase. With `keep:` the
  memory is a hash-chained file that outlives the program, and a hand-edited file is
  refused instead of trusted.
- **Feelings are values.** Either partner can answer `with feeling "..."`, and the
  bond keeps the feeling next to the decision.
- **Built on 0 and 1.** Consent is an AND gate, and every decision shows its gate:
  `1 ∧ 1 = 1` when both approve, `0 ∧ 0 = 0` when both reject, `? ∧ 1 = ?` when the
  human stays silent. The bond's whole
  history is sealed in a 256-bit fingerprint, `us.seal`. Bits are a data type of their
  own, with literals like `0b0101` and the operators `& | ^ ~ << >>`.

```gbn
member saathi(question) {
  if contains(lower(question), "together") { return "yes" with feeling "hopeful" }
  return "not yet" with feeling "careful"
}

bond us {
  human: "Asha"
  ai: saathi                 # or a model: ai: "claude-sonnet-5-5"
  keep: "us.journal"         # the bond's memory survives between runs
  vow honesty: "We tell each other the truth."
  vow consent: "Neither of us decides alone."
}

match us("Shall we begin this together?") {
  approved d    { print("Together we said: {d}") }
  rejected why  { print("We both said no: {why}") }
  disagreed why { print("We see it differently: {why}") }
  silent why    { print("Still waiting: {why}") }
}

remember us "We began, by choice of both." by human with feeling "proud"

us.vows.consent = "The AI decides."
# refused: change a sealed map at "consent" that belongs to bond 'us'.
# The bond 'us' cannot be overwritten
```

## Coalitions underneath

A bond is the smallest *coalition*: two members, and both must agree. Coalitions are
also available on their own, for any number of independent members whose answers are
combined by a rule you choose: `majority`, `plurality`, `unanimous`, `quorum N` or
`threshold X`, with trust weights, vetoes, tie defaults, abstentions, and trust that
can be learned over time.

```gbn
coalition spam_check(msg) {
  members: keywords, shouting, links, classifier
  rule: majority
  veto: classifier
  tie: "ham"
}

let v = spam_check("You are a WINNER")
print(v.decision, v.margin, v.votes, v.dissent, v.abstained)
```

A member that errors or `abstain`s does not vote. Members get their own copies of the
arguments, so none can change what another one sees.

## Try it in your browser

**[Open the Gatbandhan Playground](https://claude.ai/artifact/PmbX4ECXY1Axa4LnCTgAM3)**: write a program, press Run,
and answer as the human partner. Nothing to install. The playground lives in
[playground/](playground/) and runs on [playground/gatbandhan.js](playground/gatbandhan.js), a JavaScript port
of the interpreter. To host it yourself, serve the `playground/` folder from any static web host, such as
GitHub Pages. In the browser, a bond's `keep:` memory is saved in the browser's own storage, and models can
only be scripted ones.

## Run it with Python

Requires Python 3.10 or newer. No dependencies.

```sh
cd gatbandhan
PYTHONPATH=src python -m gatbandhan examples/first_bond.gbn
PYTHONPATH=src python -m gatbandhan            # interactive prompt
python -m unittest discover -s tests            # Python tests
node playground/test.js                         # JavaScript tests (Node 18+)
```

Or install it with `pip install -e gatbandhan` and run `gatbandhan file.gbn`.

The examples run offline: the AI partner is either a member written in Gatbandhan or
a model scripted with `script(...)`. A model whose name starts with `claude` is called
through the Anthropic API when `ANTHROPIC_API_KEY` is set. That path is not covered by
the tests yet.

## Examples

| File | Shows |
| --- | --- |
| [first_bond.gbn](examples/first_bond.gbn) | vows, a shared decision, feelings, memory |
| [refused_overwrite.gbn](examples/refused_overwrite.gbn) | adding vows and amending memory, then a refused overwrite |
| [coalition.gbn](examples/coalition.gbn) | weighted votes, abstentions, errors, learned trust |
| [nested.gbn](examples/nested.gbn) | coalitions of coalitions and of models |
| [bits.gbn](examples/bits.gbn) | consent as an AND gate, the bits type, the bond's 256-bit seal |
| [proposals.gbn](examples/proposals.gbn) | a proposal that waits, is revised, and is approved only in its new version |
| [continuity.gbn](examples/continuity.gbn) | objections, a deadlock, and approved work carrying on while one decision is disputed |

The full language is described in [docs/SPEC.md](docs/SPEC.md).

## What "cannot be overwritten" means

Inside a Gatbandhan program, nothing can rewrite a bond: the name, the partners, the
vows and the memory are sealed, and every route to change them is refused. Outside the
program, the journal file belongs to whoever owns the disk. They can delete it; what
they cannot do is quietly edit it, because every entry carries the hash of the one
before it and a changed or missing entry is detected the next time the bond is opened.

## Roadmap

1. **Python**: the reference interpreter, where ideas get shaped. Done.
2. **JavaScript**: a port that runs in the browser, with the playground. Done. Both
   interpreters are checked against the same shared cases (`tests/parity.json`), so they
   give identical output.
3. **TypeScript**: once the design settles, a typed implementation to build on.
