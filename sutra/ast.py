"""AST node definition.

Every node is a ``Node`` with a ``kind`` string and keyword attributes. The
interpreter dispatches on ``kind`` (``exec_<kind>`` / ``eval_<kind>``).
"""


class Node:
    __slots__ = ("kind", "line", "attrs")

    def __init__(self, kind, line, **attrs):
        self.kind = kind
        self.line = line
        self.attrs = attrs

    def __getattr__(self, name):
        try:
            return self.attrs[name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self):
        inner = ", ".join(f"{k}={v!r}" for k, v in self.attrs.items())
        return f"{self.kind}({inner})"
