"""Built-in functions."""

from .errors import GbnRuntimeError
from .values import Bits, Bond, Builtin, Coalition, show, type_name, unseal

VERSION = "0.1.0"


def install(interp):
    def plain(name, fn):
        interp.globals.vars[name] = Builtin(name, fn)

    def special(name, fn):
        interp.globals.vars[name] = Builtin(name, fn, pass_interp=True)

    special("print", lambda it, args, line: it.print(" ".join(show(a) for a in args)))
    plain("len", _len)
    plain("str", lambda v: show(v))
    plain("num", _num)
    plain("type_of", type_name)
    plain("lower", lambda s: _s(s, "lower").lower())
    plain("upper", lambda s: _s(s, "upper").upper())
    plain("trim", lambda s: _s(s, "trim").strip())
    plain("contains", _contains)
    plain("starts_with", lambda s, p: _s(s, "starts_with").startswith(_s(p, "starts_with")))
    plain("ends_with", lambda s, p: _s(s, "ends_with").endswith(_s(p, "ends_with")))
    plain("split", lambda s, sep=None: _s(s, "split").split(sep) if sep is not None else s.split())
    plain("join", lambda xs, sep="": _s(sep, "join").join(show(x) for x in _l(xs, "join")))
    plain("replace", lambda s, a, b: _s(s, "replace").replace(_s(a, "replace"), _s(b, "replace")))
    plain("keys", lambda m: list(_m(m, "keys").keys()))
    plain("values", lambda m: list(_m(m, "values").values()))
    plain("push", _push)
    plain("range", _range)
    plain("round", lambda x, d=0: _round(x, d))
    plain("abs", lambda x: abs(_n(x, "abs")))
    plain("min", lambda *xs: min(_nums(xs, "min")))
    plain("max", lambda *xs: max(_nums(xs, "max")))
    plain("sum", lambda xs: sum(_n(x, "sum") for x in _l(xs, "sum")))
    plain("sort", lambda xs: sorted(_l(xs, "sort")))
    plain("copy", unseal)
    special("error", lambda it, args, line: _raise(args, line))
    special("hear", _hear)
    special("consult", _consult)
    special("script", _script)
    special("script_human", lambda it, args, line: it.human.script(_l(args[0], "script_human")))
    special("trust", _trust)
    special("history", _history)
    special("vows", lambda it, args, line: _bond(it, args, line, "vows").get("vows"))
    special("memory", lambda it, args, line: _bond(it, args, line, "memory").get("memory"))
    plain("bits", _bits)
    plain("version", lambda: VERSION)


def _s(v, fn):
    if not isinstance(v, str):
        raise GbnRuntimeError(f"{fn} needs a string, got a {type_name(v)}")
    return v


def _l(v, fn):
    if not isinstance(v, list):
        raise GbnRuntimeError(f"{fn} needs a list, got a {type_name(v)}")
    return v


def _m(v, fn):
    if not isinstance(v, dict):
        raise GbnRuntimeError(f"{fn} needs a map, got a {type_name(v)}")
    return v


def _n(v, fn):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise GbnRuntimeError(f"{fn} needs a number, got a {type_name(v)}")
    return v


def _nums(xs, fn):
    if len(xs) == 1 and isinstance(xs[0], list):
        xs = xs[0]
    if not xs:
        raise GbnRuntimeError(f"{fn} needs at least one number")
    return [_n(x, fn) for x in xs]


def _len(v):
    if isinstance(v, (str, list, dict, Bits)):
        return len(v)
    raise GbnRuntimeError(f"len needs a string, list or map, got a {type_name(v)}")


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, Bits):
        return v.value
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            raise GbnRuntimeError(f"cannot turn {show(v, True)} into a number")
        return int(f) if f.is_integer() and "." not in v else f
    raise GbnRuntimeError(f"cannot turn a {type_name(v)} into a number")


def _contains(hay, needle):
    if isinstance(hay, str):
        return _s(needle, "contains") in hay
    if isinstance(hay, list):
        return needle in hay
    if isinstance(hay, dict):
        return needle in hay
    raise GbnRuntimeError(f"contains needs a string, list or map, got a {type_name(hay)}")


def _push(xs, v):
    _l(xs, "push").append(v)
    return xs


def _range(a, b=None):
    if b is None:
        a, b = 0, a
    return list(range(int(_n(a, "range")), int(_n(b, "range"))))


def _round(x, d):
    r = round(_n(x, "round"), int(d))
    return int(r) if d == 0 else r


def _raise(args, line):
    raise GbnRuntimeError(show(args[0]) if args else "error", line)


def _hear(it, args, line):
    prompt = show(args[0]) + "\n> " if args else "> "
    reply = it.human.line(prompt)
    if isinstance(reply, dict):
        return reply.get("answer")
    return reply


def _consult(it, args, line):
    if len(args) != 2 or not isinstance(args[0], str):
        raise GbnRuntimeError("consult(model, text) needs a model name and the text to send", line)
    reply = it.models.consult(args[0], show(args[1]), line=line)
    return reply.get("answer") if isinstance(reply, dict) else reply


def _script(it, args, line):
    if len(args) != 2 or not isinstance(args[0], str) or not isinstance(args[1], list):
        raise GbnRuntimeError("script(model, replies) needs a model name and a list of replies", line)
    it.models.script(args[0], unseal(args[1]))


def _trust(it, args, line):
    c = args[0] if args else None
    if not isinstance(c, Coalition):
        raise GbnRuntimeError("trust(c) needs a coalition", line)
    return {k: (int(v) if float(v).is_integer() else round(v, 6)) for k, v in c.learned.items()}


def _history(it, args, line):
    c = args[0] if args else None
    if not isinstance(c, Coalition):
        raise GbnRuntimeError("history(c) needs a coalition", line)
    return list(c.history)


def _bond(it, args, line, fn):
    b = args[0] if args else None
    if not isinstance(b, Bond):
        raise GbnRuntimeError(f"{fn}(b) needs a bond", line)
    return b


def _bits(v, width=None):
    """Make bits from a whole number, a list of 0s and 1s, a string like "0101",
    or a bond's seal (64 hex digits, 256 bits)."""
    if isinstance(v, Bits):
        n, size = v.value, v.width
    elif isinstance(v, list):
        if not v or any(x not in (0, 1) or isinstance(x, bool) for x in v):
            raise GbnRuntimeError("bits from a list needs a non-empty list of 0s and 1s")
        n, size = int("".join(str(x) for x in v), 2), len(v)
    elif isinstance(v, str):
        if v and set(v) <= {"0", "1"}:
            n, size = int(v, 2), len(v)
        elif len(v) == 64 and all(c in "0123456789abcdef" for c in v):
            n, size = int(v, 16), 256
        else:
            raise GbnRuntimeError("bits from text needs 0s and 1s, or a bond's seal")
    else:
        n = _n(v, "bits")
        if not float(n).is_integer() or n < 0:
            raise GbnRuntimeError("bits needs a whole number of 0 or more")
        n = int(n)
        size = max(1, n.bit_length())
    if width is not None:
        width = int(_n(width, "bits"))
        if width < 1:
            raise GbnRuntimeError("bits need a width of at least 1")
        if n >= (1 << width):
            raise GbnRuntimeError(f"{n} does not fit in {width} bits")
        size = width
    return Bits(n, size)
