"""Turns Gatbandhan source text into tokens.

Newlines are not significant. A string keeps its raw text; the parser splits
it into literal parts and ``{expression}`` interpolations.
"""

from dataclasses import dataclass

from .errors import GbnSyntaxError

KEYWORDS = {
    "let", "fn", "member", "coalition", "bond", "vow", "remember", "amend",
    "with", "by", "return", "abstain", "if", "else",
    "while", "for", "in", "break", "continue", "match",
    "true", "false", "none", "and", "or", "not",
}

TWO_CHAR = {"==", "!=", "<=", ">=", "=>", "<<", ">>"}
ONE_CHAR = set("+-*/%<>=()[]{},.:;&|^~")


@dataclass
class Token:
    kind: str  # NUMBER STRING IDENT KEYWORD OP EOF
    value: object
    line: int

    def is_op(self, *ops):
        return self.kind == "OP" and self.value in ops

    def is_kw(self, *kws):
        return self.kind == "KEYWORD" and self.value in kws


ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "{": "\x00", "}": "\x01"}


def tokenize(src, line=1):
    tokens = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch in " \t\r":
            i += 1
        elif ch == "#":
            while i < n and src[i] != "\n":
                i += 1
        elif ch == "0" and src[i + 1:i + 2] in ("b", "B"):
            j = i + 2
            while j < n and src[j] in "01_":
                j += 1
            digits = src[i + 2:j].replace("_", "")
            if not digits or (j < n and (src[j].isalnum())):
                raise GbnSyntaxError("a binary number is 0b followed by 0s and 1s", line)
            tokens.append(Token("BITS", (int(digits, 2), len(digits)), line))
            i = j
        elif ch.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
            if j + 1 < n and src[j] == "." and src[j + 1].isdigit():
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
                value = float(src[i:j].replace("_", ""))
            else:
                value = int(src[i:j].replace("_", ""))
            tokens.append(Token("NUMBER", value, line))
            i = j
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            tokens.append(Token("KEYWORD" if word in KEYWORDS else "IDENT", word, line))
            i = j
        elif ch == '"':
            start_line = line
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise GbnSyntaxError("unterminated string", start_line)
                c = src[j]
                if c == '"':
                    break
                if c == "\\":
                    if j + 1 >= n or src[j + 1] not in ESCAPES:
                        bad = src[j + 1] if j + 1 < n else ""
                        raise GbnSyntaxError(f"unknown escape '\\{bad}'", line)
                    buf.append(ESCAPES[src[j + 1]])
                    j += 2
                    continue
                if c == "\n":
                    line += 1
                buf.append(c)
                j += 1
            tokens.append(Token("STRING", "".join(buf), start_line))
            i = j + 1
        elif src[i:i + 2] in TWO_CHAR:
            tokens.append(Token("OP", src[i:i + 2], line))
            i += 2
        elif ch in ONE_CHAR:
            tokens.append(Token("OP", ch, line))
            i += 1
        else:
            raise GbnSyntaxError(f"unexpected character {ch!r}", line)
    tokens.append(Token("EOF", None, line))
    return tokens
