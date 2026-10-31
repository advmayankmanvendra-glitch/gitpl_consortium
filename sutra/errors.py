"""Error types shared by every stage of the Sutra pipeline, and their rendering.

Every error carries an optional source position (``line``, ``col`` and the
``length`` of the offending text), an optional ``hint`` suggesting a fix, and,
for runtime errors, the chain of function calls (``frames``) it unwound
through. ``format_error`` turns all of that into a readable report with a
snippet of the source and a caret under the problem.
"""

import difflib
import os


def position_of(pos):
    """Return ``(line, col, length)`` for an int line, a token, a node or ``None``."""
    if pos is None or isinstance(pos, int):
        return pos, None, None
    return getattr(pos, "line", None), getattr(pos, "col", None), getattr(pos, "length", None)


class SutraError(Exception):
    """Base class for all errors raised while lexing, parsing or running Sutra code."""

    def __init__(self, message, pos=None, hint=None, incomplete=False):
        self.message = message
        self.line, self.col, self.length = position_of(pos)
        self.hint = hint
        # True when the source simply ended too early (e.g. an unclosed block);
        # the REPL uses this to keep reading more lines instead of failing.
        self.incomplete = incomplete
        self.frames = []  # (function name, call position) from innermost to outermost
        super().__init__(message)

    def locate(self, pos):
        """Fill in the position from ``pos`` if this error does not have one yet."""
        if self.line is None:
            self.line, self.col, self.length = position_of(pos)
        return self

    def __str__(self):
        text = self.message
        if self.line is not None:
            where = f"line {self.line}" + (f", column {self.col}" if self.col else "")
            text = f"{where}: {text}"
        if self.hint:
            text = f"{text} (hint: {self.hint})"
        return text

    @property
    def label(self):
        return {
            "SutraSyntaxError": "syntax error",
            "SutraRuntimeError": "error",
            "ThrownError": "uncaught error",
            "ModelError": "model error",
        }.get(type(self).__name__, "error")


class SutraSyntaxError(SutraError):
    """Raised by the lexer or parser for malformed source code."""


class SutraRuntimeError(SutraError):
    """Raised by the interpreter while running a program."""


class ModelError(SutraRuntimeError):
    """Raised when a model backend fails or returns something unusable."""


# ------------------------------------------------------------------ suggestions
def did_you_mean(name, candidates):
    """Return a ``did you mean 'x'?`` hint, or ``None`` if nothing is close."""
    matches = difflib.get_close_matches(name, [c for c in candidates if c != name], n=1, cutoff=0.7)
    return f"did you mean '{matches[0]}'?" if matches else None


# ------------------------------------------------------------------ rendering
class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def red(self, text):
        return self._wrap("1;31", text)

    def blue(self, text):
        return self._wrap("1;34", text)

    def cyan(self, text):
        return self._wrap("1;36", text)

    def bold(self, text):
        return self._wrap("1", text)


def use_color(stream):
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def format_error(error, source=None, filename=None, color=False):
    """Render an error as a multi-line report with a source snippet and caret.

    Example::

        syntax error: expected ')' but found '{'
          --> greet.sutra:3:14
           |
         3 | print(greet("Ada" {
           |                   ^
           = hint: did you forget a ')' to close the call?
    """
    s = Style(color)
    lines = [f"{s.red(error.label)}{s.bold(': ' + error.message)}"]
    line, col = error.line, error.col
    src_lines = source.split("\n") if source is not None else None
    have_snippet = src_lines is not None and line is not None and 1 <= line <= len(src_lines)
    gutter = len(str(line)) if have_snippet else 1
    pad = " " * gutter

    if line is not None:
        where = filename or "<input>"
        loc = f"{where}:{line}" + (f":{col}" if col else "")
        lines.append(f"{pad}{s.blue('-->')} {loc}")
    if have_snippet:
        text = src_lines[line - 1].rstrip().expandtabs(4)
        lines.append(f"{pad} {s.blue('|')}")
        lines.append(f"{s.blue(str(line))} {s.blue('|')} {text}")
        if col:
            raw = src_lines[line - 1]
            # Account for tabs expanded before the error column.
            offset = len(raw[: col - 1].expandtabs(4))
            width = max(1, min(error.length or 1, max(1, len(text) - offset)))
            lines.append(f"{pad} {s.blue('|')} {' ' * offset}{s.red('^' * width)}")
    for name, pos in error.frames:
        call_line = position_of(pos)[0]
        if call_line is not None:
            lines.append(f"{pad} {s.blue('=')} in {name}(), called from line {call_line}")
    if error.hint:
        lines.append(f"{pad} {s.blue('=')} {s.cyan('hint')}: {error.hint}")
    return "\n".join(lines)
