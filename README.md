> This repository holds two languages. **[Gatbandhan](gatbandhan/README.md)** is a
> language for a bond between a human and an AI. **Sutra**, below, is an earlier
> language for AI workflows.

# Sutra

**A small programming language for AI workflows.** In Sutra, prompts, model calls,
typed outputs, tools and agents are part of the syntax, so a program that uses an
LLM reads like the idea behind it.

```sutra
type Review = {
  sentiment: "positive" | "negative" | "mixed"
  score: num
  highlights: [str]
}

prompt analyze(review) {
  system: "You analyze restaurant reviews."
  user: "Analyze this review and score it 1 to 5:\n{review}"
}

let r = ask analyze("The biryani was incredible!") as Review
print("{r.sentiment}: {r.score}/5")
```

`ask ... as Review` sends the type's JSON Schema to the model, parses and validates
the reply, and retries with the error message if the reply doesn't fit. You get back
a real map, not a string to parse.

## Highlights

- **Prompts as declarations** with parameters, defaults, system messages and few-shot turns.
- **`ask`** sends any prompt or string to a model: `ask "Summarize {doc}" using fast`.
- **Structured output** with `type` declarations: objects, lists, optional fields and string enums.
- **Tools** are ordinary Sutra functions with typed parameters and a description.
- **Agents** run the tool-use loop for you, with a step limit and an optional trace.
- **Offline by default**: a mock model makes every program runnable and testable without an
  API key, and `mock([...])` scripts replies and tool calls for tests.
- **Claude backend** using only the Python standard library. No dependencies.

## Quick start

Requires Python 3.10+.

```bash
python -m sutra examples/hello.sutra          # run a program
python -m sutra examples/agent.sutra          # agent with tools, offline
python -m sutra                               # interactive REPL
python -m sutra --check my_program.sutra      # syntax check only

pip install -e .                              # optional: installs the `sutra` command
```

To use Claude, set your API key and pick a model:

```bash
export ANTHROPIC_API_KEY=...
python -m sutra examples/classify.sutra --model anthropic:claude-sonnet-5-5
```

or choose it inside the program with `use "anthropic:claude-sonnet-5-5"`.

## A tour

```sutra
# Ordinary programming
let names = ["Asha", "Ravi"]
fn greet(name, greeting = "Namaste") { return "{greeting}, {name}!" }
for name in names { print(greet(name)) }

# Models
use "anthropic:claude-sonnet-5-5"
let fast = model("claude-haiku-5-5", {max_tokens: 300})

# Prompts and asks
prompt translate(text, language = "Hindi") """
  Translate into {language}. Reply with the translation only.
  {text}
"""
print(ask translate("Good morning") using fast)

# Tools and agents
tool weather(city: str) "Current weather for a city" {
  return "31 degrees and sunny in {city}"      # call a real API here
}

agent planner {
  system: "You help people plan their day."
  tools: [weather]
  trace: true
}

print(planner("Should I carry an umbrella in Mumbai today?"))

# Errors from models are catchable
try {
  let n = ask "Pick a number" as num
} catch err {
  print("model failed: {err}")
}
```

The full language reference is in [docs/SPEC.md](docs/SPEC.md).

## Examples

| File | Shows |
|------|-------|
| [examples/hello.sutra](examples/hello.sutra) | variables, functions, loops, maps |
| [examples/classify.sutra](examples/classify.sutra) | prompts with system messages and typed outputs |
| [examples/pipeline.sutra](examples/pipeline.sutra) | a multi-step triage pipeline with branching |
| [examples/agent.sutra](examples/agent.sutra) | tools and an agent, with a scripted mock model |

## Project layout

```
sutra/
  lexer.py         source -> tokens (including string interpolation)
  parser.py        tokens -> AST
  interpreter.py   tree-walking evaluator, ask, structured output, agent loop
  types.py         runtime types: JSON Schema, validation, placeholder values
  models.py        model backends: MockModel and AnthropicModel
  builtins.py      built-in functions
  cli.py           command line and REPL
docs/SPEC.md       language specification
examples/          runnable programs
tests/             unit tests (python -m unittest discover -s tests)
```

## Adding a model backend

Subclass `sutra.models.Model` and implement
`complete(system, messages, tools=None, schema=None) -> Response`, then register a
prefix in `make_model`. Messages and tool calls use the Anthropic Messages API
shape, so the agent loop works unchanged with any backend that maps to it.

## Roadmap ideas

- Streaming replies and parallel `ask` over lists
- More providers (OpenAI-compatible, local models)
- Modules and imports
- Response caching and cost tracking per program
