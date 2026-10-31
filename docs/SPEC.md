# Sutra language specification (v0.1)

Sutra is a small, dynamically typed scripting language for writing programs that use
large language models. Ordinary programming (variables, functions, loops, maps) works
the way you expect; the AI parts (prompts, model calls, typed outputs, tools and
agents) are part of the syntax instead of library calls.

Source files use the `.sutra` extension and are UTF-8 text.

## 1. Lexical structure

- **Comments** start with `#` and run to the end of the line.
- **Statements** are separated by newlines or `;`. Newlines are otherwise not
  significant, except that a `(` or `[` at the start of a line begins a new
  statement instead of calling or indexing the previous line.
- **Identifiers**: letters, digits and `_`, not starting with a digit.
- **Numbers**: `42`, `3.14`, `1_000_000`.
- **Strings**: `"..."` on one line, or `"""..."""` across lines. Triple-quoted
  strings drop their first and last blank lines and remove common indentation,
  so they can be indented with the code around them.
- **Interpolation**: `{expr}` inside any string evaluates `expr`.
  `"Hi {user.name}, you have {len(items)} items"`. Write `\{` and `\}` for literal
  braces. Other escapes: `\n \t \r \" \\ \0`.
- **Keywords**: `let fn return if else while for in break continue true false none
  and or not prompt tool agent type use ask using as try catch throw`.

## 2. Values

| Type     | Examples                        | Notes                                      |
|----------|---------------------------------|--------------------------------------------|
| `none`   | `none`                          |                                            |
| `bool`   | `true`, `false`                 |                                            |
| `num`    | `1`, `2.5`                      | integers and floats; `7 / 2` is `3.5`      |
| `str`    | `"text"`                        |                                            |
| `list`   | `[1, "a", [2]]`                 | mutable                                    |
| `map`    | `{name: "A", "two words": 2}`   | mutable, insertion ordered                 |
| `fn`     | `fn(x) { return x * 2 }`        | closures                                   |
| `prompt` | declared with `prompt`          | calling one renders a prompt value         |
| `tool`   | declared with `tool`            | callable like a function                   |
| `agent`  | declared with `agent`           | callable with one task                     |
| `model`  | `model("anthropic:...")`        | a model backend                            |
| `type`   | declared with `type`            | used by `ask ... as T` and tool parameters |

Falsy values: `none`, `false`, `0`, `""`, `[]`, `{}`. Everything else is truthy.

## 3. Statements

```
let name = expr                 # declare a variable in the current scope
name = expr                     # assign to an existing variable
name += expr; name -= expr
list[i] = expr; map.key = expr; map["key"] = expr

fn name(a, b = 1) { ... }       # function; parameters may have defaults
return expr

if cond { ... } else if cond { ... } else { ... }
while cond { ... }
for item in list { ... }        # also strings and maps (keys)
for i, item in list { ... }     # index and item; for maps: key and value
break; continue

try { ... } catch err { ... }   # err is the thrown value or the error message
throw expr
```

Blocks create a new scope. Assigning to a name that was never declared with
`let` is an error, which catches typos.

## 4. Expressions

Precedence from lowest to highest:

1. `or`
2. `and`
3. `not`
4. `== != < > <= >= in` and `not in`
5. `+ -`
6. `* / %`
7. unary `-` and `ask`
8. calls `f(x)`, indexing `x[i]`, fields `x.name`
9. literals, names, `( ... )`, list and map literals, `fn` lambdas

`+` concatenates when either side is a string, and also joins two lists or
merges two maps. `"ab" * 3` and `[0] * 3` repeat.

Calls accept positional arguments followed by named ones:
`greet("Ada", greeting: "Hello")`.

## 5. AI features

### 5.1 Models

```
use "mock"                                    # offline model (default)
use "anthropic:claude-sonnet-5-5"             # Claude, needs ANTHROPIC_API_KEY
use model("anthropic:claude-opus-5-5", {max_tokens: 2048, temperature: 0})
let fast = model("claude-haiku-5-5")
```

`use` sets the default model for the rest of the program. The model is chosen in
this order: an explicit `using` clause, the last `use`, the `--model` command line
flag, the `SUTRA_MODEL` environment variable, and finally `"mock"`.

Model specs: `"mock"`, `"anthropic:<model-id>"` (also `"claude:<id>"`), or a bare
`"claude-..."` model id. `mock(script)` builds a scripted offline model (see 5.6).

### 5.2 Prompts

A prompt is a named, parameterized message template.

```
prompt translate(text, language = "Hindi") """
  Translate into {language}:
  {text}
"""

prompt classify(text) {
  system: "You label support tickets."
  user: "My card was charged twice"         # few-shot example
  assistant: "billing"
  user: "{text}"
}
```

The block form lists `system`, `user` and `assistant` messages in order; there
must be at least one `user` message. Calling a prompt (`translate("hello")`)
returns a prompt value with fields `.text`, `.system` and `.messages`; nothing
is sent to a model until it is asked.

### 5.3 `ask`

```
ask <expr> [using <model>] [as <type>]
```

`ask` sends a prompt value, or any value converted to a string, to a model and
returns the reply. Without `as`, or with `as str`, the result is the reply text.

```
let reply = ask "Write a haiku about {topic}"
let hindi = ask translate("good morning") using fast
```

### 5.4 Types and structured output

```
type Sentiment = "positive" | "negative" | "mixed"
type Review = {
  sentiment: Sentiment
  score: num
  highlights: [str]
  complaint?: str          # optional: none when absent
}

let r = ask "Analyze: {text}" as Review
print(r.sentiment, r.score)
```

Type expressions: `str`, `num`, `bool`, `any`, `[T]` (list of T),
`{field: T, optional?: T}` (object), `"a" | "b"` (one of these strings), and
names declared with `type`.

With `as T` the interpreter:

1. sends the JSON Schema of `T` with the request and asks for JSON only;
2. parses the reply, tolerating code fences and surrounding prose;
3. validates and converts it (for example the string `"4"` for a `num` field);
4. if it does not fit, sends the error back to the model and tries again, up to
   3 attempts in total, then raises an error that `try`/`catch` can handle.

### 5.5 Tools

A tool is a function with typed parameters and a description that a model can
call.

```
tool weather(city: str, unit: "c" | "f" = "c") "Current weather for a city" {
  return "31 degrees {unit} and sunny in {city}"
}
```

Arguments are validated against the parameter types whether the tool is called
by a model or directly from Sutra code. A parameter without a type accepts
anything. Parameters without defaults are required.

### 5.6 Agents

An agent pairs a model with tools and runs the tool-use loop for you.

```
agent assistant {
  model: "anthropic:claude-sonnet-5-5"   # optional; defaults to the default model
  system: "You are a helpful travel assistant."
  tools: [weather]
  max_steps: 8                           # optional, default 8
  trace: true                            # optional, print each tool call
}

let answer = assistant("Should I carry an umbrella in Mumbai today?")
```

Each step sends the conversation and tool definitions to the model. When the
model asks for tools, the agent runs them and sends back the results; a tool
that throws reports the error to the model instead of stopping the program.
When the model replies without a tool call, that reply is the agent's result.
Exceeding `max_steps` raises an error.

`mock([...])` returns replies from a script, which makes agents testable
offline. A string is a text reply, a map with a `tool` key is a tool call
(`{tool: "weather", args: {city: "Pune"}}`), and any other value is sent as JSON.
With no script, the mock echoes plain asks and returns placeholder values that
match the requested type.

## 6. Built-in functions

| Function | Description |
|----------|-------------|
| `print(a, b, ...)` | print values separated by spaces |
| `len(x)` | length of a string, list or map |
| `str(x)`, `num(x)`, `int(x)` | conversions |
| `range(n)`, `range(a, b, step)` | list of numbers |
| `push(list, x)`, `pop(list)` | add or remove the last item |
| `join(list, sep)`, `split(s, sep)` | string and list conversion |
| `upper`, `lower`, `trim`, `replace(s, old, new)`, `starts_with`, `ends_with`, `words` | strings |
| `keys(m)`, `values(m)`, `contains(c, x)`, `slice(x, a, b)` | collections |
| `map(list, fn)`, `filter(list, fn)`, `sort(list, key_fn)` | higher-order helpers |
| `json(x, indent)`, `parse_json(s)` | JSON |
| `type_of(x)` | the type name of a value |
| `model(spec, options)`, `mock(script)` | model backends |
| `assert(cond, message)` | raise an error when `cond` is falsy |
| `read(path)`, `env(name, default)` | read a file or an environment variable |

## 7. Errors

Syntax errors are reported before the program runs. Runtime errors carry the
line number of the statement that failed. `try`/`catch` catches runtime errors,
model errors and values raised with `throw`.
