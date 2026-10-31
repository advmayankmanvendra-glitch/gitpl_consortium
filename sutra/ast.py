"""AST node definition.

Every node is a ``Node`` with a ``kind`` string, a source position and keyword
attributes. The
interpreter dispatches on ``kind`` (``exec_<kind>`` / ``eval_<kind>``).
"""


class Node:
    __slots__ = ("kind", "line", "col", "length", "attrs")

    def __init__(self, kind, pos, **attrs):
        """``pos`` is a token or node to take the position from, or a bare line number."""
        self.kind = kind
        if isinstance(pos, int):
            self.line, self.col, self.length = pos, None, None
        else:
            self.line, self.col, self.length = pos.line, pos.col, getattr(pos, "length", None)
        self.attrs = attrs

    def __getattr__(self, name):
        try:
            return self.attrs[name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self):
        inner = ", ".join(f"{k}={v!r}" for k, v in self.attrs.items())
        return f"{self.kind}({inner})"
