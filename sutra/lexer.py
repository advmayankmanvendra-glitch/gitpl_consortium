"""Turns Sutra source text into a list of tokens.

Strings are split into parts at lex time: a part is either a plain ``str`` or an
``Interp`` holding the source of an embedded ``{expression}``. The parser later
parses those embedded sources into expressions.
"""

import textwrap
from dataclasses import dataclass, field

from .errors import SutraSyntaxError

KEYWORDS = {
    "let", "fn", "return", "if", "else", "while", "for", "in", "break",
    "continue", "true", "false", "none", "and", "or", "not", "prompt",
    "tool", "agent", "type", "use", "ask", "using", "as", "try", "catch",
    "throw",
}

TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "+=", "-=", "->"}
ONE_CHAR_OPS = set("+-*/%<>=()[]{},.:;|?")


@dataclass
class Interp:
    source: str
    line: int
    col: int = None  # column of the first character of ``source``, if known


@dataclass
class Pos:
    """A bare source position, for errors that do not belong to a token."""

    line: int
    col: int = None
    length: int = 1


@dataclass
class Token:
    kind: str  # NUMBER, STRING, IDENT, KEYWORD, OP, EOF
    value: object
    line: int
    nl_before: bool = False
    parts: list = field(default_factory=list)  # only for STRING
    col: int = None
    length: int = 1

    def is_op(self, *ops):
        return self.kind == "OP" and self.value in ops

    def is_kw(self, *kws):
        return self.kind == "KEYWORD" and self.value in kws

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, line={self.line})"


ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "{": "{", "}": "}", "r": "\r", "0": "\0"}


def split_string(raw, line, col=None):
    """Split raw string contents into literal text and {interpolation} parts.

    ``col`` is the column of ``raw[0]`` in the source; it is ``None`` for
    triple-quoted strings, whose text has been dedented.
    """
    parts = []
    buf = []
    i = 0
    cur_line = line
    line_start = 0  # index in raw where the current line starts

    def here(index, length=1):
        c = None
        if col is not None:
            c = (col if cur_line == line else 1) + index - line_start
        return Pos(cur_line, c, length)

    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "\n":  # line continuation
                i += 2
                cur_line += 1
                line_start = i
                continue
            if nxt not in ESCAPES:
                raise SutraSyntaxError(
                    f"unknown escape sequence '\\{nxt}'",
                    here(i, 2),
                    hint="valid escapes are \\n \\t \\r \\0 \\\" \\\\ \\{ \\}",
                )
            buf.append(ESCAPES[nxt])
            i += 2
            continue
        if ch == "{":
            depth = 1
            j = i + 1
            quote = False
            while j < len(raw) and depth:
                c = raw[j]
                if c == '"' and raw[j - 1] != "\\":
                    quote = not quote
                elif not quote and c == "{":
                    depth += 1
                elif not quote and c == "}":
                    depth -= 1
                j += 1
            if depth:
                raise SutraSyntaxError(
                    "unclosed '{' in string interpolation",
                    here(i),
                    hint="close it with '}', or write '\\{' for a literal brace",
                )
            source = raw[i + 1 : j - 1]
            if not source.strip():
                raise SutraSyntaxError(
                    "empty '{}' in string", here(i, 2), hint="write '\\{' and '\\}' for literal braces"
                )
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append(Interp(source, cur_line, here(i + 1).col))
            if "\n" in source:
                cur_line += source.count("\n")
                line_start = i + 1 + source.rfind("\n") + 1
            i = j
            continue
        if ch == "}":
            raise SutraSyntaxError("unmatched '}' in string", here(i), hint="write '\\}' for a literal brace")
        if ch == "\n":
            cur_line += 1
            line_start = i + 1
        buf.append(ch)
        i += 1
    if buf or not parts:
        parts.append("".join(buf))
    return parts


def dedent_block(raw):
    """Dedent a triple-quoted string and drop the first and last blank lines."""
    if raw.startswith("\n"):
        raw = raw[1:]
    lines = raw.split("\n")
    if lines and not lines[-1].strip():
        lines = lines[:-1]
    return textwrap.dedent("\n".join(lines))


# Characters people often bring from other languages, with what to write instead.
CHAR_HINTS = {
    "'": "strings use double quotes, e.g. \"hello\"",
    "&": "use 'and' for logical and",
    "!": "use 'not' for negation (or '!=' for not-equal)",
    "^": "Sutra has no '^' operator; multiply instead, e.g. x * x",
    "@": "Sutra has no decorators or '@' operator",
    "$": "interpolate with braces inside a string, e.g. \"Hi {name}\"",
    "`": "strings use double quotes; use \"\"\" for multi-line text",
    "\\": "a backslash is only valid inside a string",
}
TWO_CHAR_HINTS = {
    "&&": "use 'and' instead of '&&'",
    "||": "use 'or' instead of '||'",
    "**": "Sutra has no power operator; multiply instead, e.g. x * x",
    "//": "comments start with '#'",
    "=>": "lambdas are written fn(x) { return x * 2 }",
}


def tokenize(source):
    tokens = []
    i = 0
    line = 1
    line_start = 0  # index of the first character of the current line
    nl_before = True
    n = len(source)

    def col_of(index):
        return index - line_start + 1

    def add(kind, value, start, parts=None):
        nonlocal nl_before
        tokens.append(Token(kind, value, line, nl_before, parts or [], col_of(start), max(1, i - start)))
        nl_before = False

    while i < n:
        ch = source[i]
        if ch == "\n":
            line += 1
            i += 1
            line_start = i
            nl_before = True
            continue
        if ch in " \t\r":
            i += 1
            continue
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        start = i
        if ch.isdigit():
            while i < n and (source[i].isdigit() or source[i] == "_"):
                i += 1
            is_float = False
            if i + 1 < n and source[i] == "." and source[i + 1].isdigit():
                is_float = True
                i += 1
                while i < n and (source[i].isdigit() or source[i] == "_"):
                    i += 1
            if i < n and (source[i].isalpha() or source[i] == "_"):
                while i < n and (source[i].isalnum() or source[i] == "_"):
                    i += 1
                raise SutraSyntaxError(
                    f"invalid number '{source[start:i]}'",
                    Pos(line, col_of(start), i - start),
                    hint="names cannot start with a digit",
                )
            text = source[start:i].replace("_", "")
            add("NUMBER", float(text) if is_float else int(text), start)
            continue
        if ch.isalpha() or ch == "_":
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            word = source[start:i]
            add("KEYWORD" if word in KEYWORDS else "IDENT", word, start)
            continue
        if ch == '"':
            start_line, start_col = line, col_of(start)
            if source.startswith('"""', i):
                end = source.find('"""', i + 3)
                while end != -1 and source[end - 1] == "\\":
                    end = source.find('"""', end + 1)
                if end == -1:
                    raise SutraSyntaxError(
                        "unterminated triple-quoted string",
                        Pos(start_line, start_col, 3),
                        hint="close it with \"\"\"",
                        incomplete=True,
                    )
                raw = dedent_block(source[i + 3 : end])
                consumed = source[i : end + 3]
                i = end + 3
                parts = split_string(raw, start_line)
            else:
                # Quotes inside an {interpolation} belong to the embedded expression.
                j = i + 1
                depth = 0
                inner_quote = False
                while j < n and (source[j] != '"' or depth > 0):
                    c = source[j]
                    if c == "\\":
                        j += 1
                    elif c == "\n":
                        break
                    elif depth > 0 and c == '"':
                        inner_quote = not inner_quote
                    elif not inner_quote and c == "{":
                        depth += 1
                    elif not inner_quote and c == "}" and depth > 0:
                        depth -= 1
                    j += 1
                if j >= n or source[j] == "\n":
                    raise SutraSyntaxError(
                        "unterminated string",
                        Pos(start_line, start_col, max(1, j - i)),
                        hint="add a closing '\"'; for text spanning several lines use \"\"\"...\"\"\"",
                    )
                raw = source[i + 1 : j]
                consumed = source[i : j + 1]
                i = j + 1
                parts = split_string(raw, start_line, start_col + 1)
            literal = "".join(parts) if all(isinstance(p, str) for p in parts) else None
            tokens.append(Token("STRING", literal, start_line, nl_before, parts, start_col, len(consumed.split("\n")[0])))
            nl_before = False
            if "\n" in consumed:
                line += consumed.count("\n")
                line_start = start + consumed.rfind("\n") + 1
            continue
        two = source[i : i + 2]
        if two in TWO_CHAR_OPS:
            i += 2
            add("OP", two, start)
            continue
        if two in TWO_CHAR_HINTS:
            raise SutraSyntaxError(f"unexpected '{two}'", Pos(line, col_of(i), 2), hint=TWO_CHAR_HINTS[two])
        if ch in ONE_CHAR_OPS:
            i += 1
            add("OP", ch, start)
            continue
        raise SutraSyntaxError(f"unexpected character {ch!r}", Pos(line, col_of(i)), hint=CHAR_HINTS.get(ch))

    tokens.append(Token("EOF", None, line, True, [], col_of(i)))
    return tokens
