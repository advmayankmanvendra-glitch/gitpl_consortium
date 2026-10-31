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


@dataclass
class Token:
    kind: str  # NUMBER, STRING, IDENT, KEYWORD, OP, EOF
    value: object
    line: int
    nl_before: bool = False
    parts: list = field(default_factory=list)  # only for STRING

    def is_op(self, *ops):
        return self.kind == "OP" and self.value in ops

    def is_kw(self, *kws):
        return self.kind == "KEYWORD" and self.value in kws

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, line={self.line})"


ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "{": "{", "}": "}", "r": "\r", "0": "\0"}


def split_string(raw, line):
    """Split raw string contents into literal text and {interpolation} parts."""
    parts = []
    buf = []
    i = 0
    cur_line = line
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "\n":  # line continuation
                i += 2
                cur_line += 1
                continue
            if nxt not in ESCAPES:
                raise SutraSyntaxError(f"unknown escape sequence '\\{nxt}'", cur_line)
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
                raise SutraSyntaxError("unclosed '{' in string interpolation", cur_line)
            source = raw[i + 1 : j - 1]
            if not source.strip():
                raise SutraSyntaxError("empty '{}' in string; write '\\{' for a literal brace", cur_line)
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append(Interp(source, cur_line))
            cur_line += source.count("\n")
            i = j
            continue
        if ch == "}":
            raise SutraSyntaxError("unmatched '}' in string; write '\\}' for a literal brace", cur_line)
        if ch == "\n":
            cur_line += 1
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


def tokenize(source):
    tokens = []
    i = 0
    line = 1
    nl_before = True
    n = len(source)

    def add(kind, value, parts=None):
        nonlocal nl_before
        tokens.append(Token(kind, value, line, nl_before, parts or []))
        nl_before = False

    while i < n:
        ch = source[i]
        if ch == "\n":
            line += 1
            nl_before = True
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch.isdigit():
            start = i
            while i < n and (source[i].isdigit() or source[i] == "_"):
                i += 1
            is_float = False
            if i + 1 < n and source[i] == "." and source[i + 1].isdigit():
                is_float = True
                i += 1
                while i < n and (source[i].isdigit() or source[i] == "_"):
                    i += 1
            text = source[start:i].replace("_", "")
            add("NUMBER", float(text) if is_float else int(text))
            continue
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            word = source[start:i]
            add("KEYWORD" if word in KEYWORDS else "IDENT", word)
            continue
        if ch == '"':
            start_line = line
            if source.startswith('"""', i):
                end = source.find('"""', i + 3)
                while end != -1 and source[end - 1] == "\\":
                    end = source.find('"""', end + 1)
                if end == -1:
                    raise SutraSyntaxError("unterminated triple-quoted string", start_line)
                raw = dedent_block(source[i + 3 : end])
                consumed = source[i : end + 3]
                i = end + 3
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
                        raise SutraSyntaxError("unterminated string (use \"\"\" for multi-line text)", line)
                    elif depth > 0 and c == '"':
                        inner_quote = not inner_quote
                    elif not inner_quote and c == "{":
                        depth += 1
                    elif not inner_quote and c == "}" and depth > 0:
                        depth -= 1
                    j += 1
                if j >= n:
                    raise SutraSyntaxError("unterminated string", start_line)
                raw = source[i + 1 : j]
                consumed = source[i : j + 1]
                i = j + 1
            parts = split_string(raw, start_line)
            literal = "".join(p for p in parts if isinstance(p, str)) if all(isinstance(p, str) for p in parts) else None
            add("STRING", literal, parts)
            line += consumed.count("\n")
            continue
        two = source[i : i + 2]
        if two in TWO_CHAR_OPS:
            add("OP", two)
            i += 2
            continue
        if ch in ONE_CHAR_OPS:
            add("OP", ch)
            i += 1
            continue
        raise SutraSyntaxError(f"unexpected character {ch!r}", line)

    tokens.append(Token("EOF", None, line, True))
    return tokens
