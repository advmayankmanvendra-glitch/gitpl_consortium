"""Built-in functions."""

from .errors import GbnRuntimeError
import copy
import hashlib

from .journal import fingerprint
from .values import (Bits, Bond, Builtin, Callable, Coalition, Function, Objection, Proposal, show,
                     type_name, unseal)

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
    special("propose", _propose)
    special("revise", _revise)
    special("proposals", lambda it, args, line: _proposals(it, args, line))
    special("unresolved", lambda it, args, line: _proposals(it, args, line, open_only=True))
    special("act", _act)
    special("revoke", _revoke)
    special("objection", _objection)
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


OPTION_KEYS = ("standing", "needs", "action", "args", "limit", "expires", "retry")


def action_hash(fn):
    """SHA-256 of a function's exact source text: what was approved is what runs."""
    return hashlib.sha256(fn.source.encode("utf-8")).hexdigest()


def _add_proposal(bond, text, version, replaces, opts):
    n = len(bond.journal.entries) + 1
    material = {"bond": bond.get("id"), "n": n, "text": text, "version": version, "replaces": replaces}
    stored = {}
    for k in OPTION_KEYS:
        v = opts.get(k)
        if v is None or v is False or v == []:
            continue
        if k == "needs":
            material[k] = [p.fingerprint for p in v]
            stored[k] = [p.id for p in v]
        else:
            material[k] = stored[k] = v
    entry = bond.journal.append("proposal", text=text, version=version, replaces=replaces,
                                fingerprint=fingerprint(material), **stored)
    return Proposal(bond, entry)


def _options(bond, opts, fn, line):
    """Read the options of propose and revise (spec section 7.7)."""
    if opts is None:
        return {}
    if not isinstance(opts, dict) or set(opts) - set(OPTION_KEYS):
        raise GbnRuntimeError(f"{fn}: options are a map with any of: {', '.join(OPTION_KEYS)}", line)
    out = {}

    def bad(msg):
        raise GbnRuntimeError(f"{fn}: {msg}", line)

    for k in ("standing", "retry"):
        if k in opts:
            if not isinstance(opts[k], bool):
                bad(f"'{k}' must be true or false")
            out[k] = opts[k]
    needs = opts.get("needs") or []
    if not isinstance(needs, list) or not all(isinstance(p, Proposal) and p.bond is bond for p in needs):
        bad("'needs' must be a list of proposals of the same bond")
    out["needs"] = list(needs)
    if opts.get("action") is not None:
        a = opts["action"]
        if not isinstance(a, Function) or not a.source:
            bad("'action' must be a function written in the program, like fn() { ... }")
        out["action"] = action_hash(a)
    if "args" in opts:
        if not isinstance(opts["args"], list) or "action" not in out:
            bad("'args' must be a list, and needs an 'action'")
        out["args"] = _plain(unseal(opts["args"]), bad)
    if "limit" in opts:
        lim = opts["limit"]
        if isinstance(lim, bool) or not isinstance(lim, int) or lim < 1:
            bad("'limit' must be a whole number of 1 or more")
        out["limit"] = lim
    if "expires" in opts:
        if not isinstance(opts["expires"], str) or not opts["expires"]:
            bad("'expires' must be a date like \"2026-12-31\"")
        out["expires"] = opts["expires"]
    return out


def _plain(v, bad):
    """Arguments are written into the bond's memory, so they must be plain data."""
    if v is None or isinstance(v, (bool, str, int)):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    if isinstance(v, list):
        return [_plain(x, bad) for x in v]
    if isinstance(v, dict) and all(isinstance(k, str) for k in v):
        return {k: _plain(x, bad) for k, x in v.items()}
    bad("'args' can hold only text, numbers, true/false, none, lists and maps")


def _propose(it, args, line):
    if len(args) not in (2, 3) or not isinstance(args[0], Bond) or not isinstance(args[1], str):
        raise GbnRuntimeError("propose(bond, text, options?) needs a bond and a text", line)
    opts = _options(args[0], args[2] if len(args) == 3 else None, "propose", line)
    return _add_proposal(args[0], args[1], 1, None, opts)


def _revise(it, args, line):
    if len(args) not in (2, 3) or not isinstance(args[0], Proposal) or not isinstance(args[1], str):
        raise GbnRuntimeError("revise(proposal, text, options?) needs a proposal and a text", line)
    p = args[0]
    status = p.status()
    if status == "replaced":
        raise GbnRuntimeError(f"proposal {p.id} was already revised; revise its newest version", line)
    if status not in ("pending", "disagreed", "deadlocked"):
        raise GbnRuntimeError(f"proposal {p.id} is already {status}; a decided proposal is not revised, "
                              "make a new one with propose()", line)
    if len(args) == 3:
        opts = _options(p.bond, args[2], "revise", line)
    else:
        opts = {k: p.entry.get(k) for k in OPTION_KEYS if k != "needs"}
        opts["needs"] = [Proposal(p.bond, p.entry_of(n)) for n in p.needs]
    return _add_proposal(p.bond, args[1], p.version + 1, p.id, opts)


def _act(it, args, line):
    """Run the exact approved action under an approved proposal. Anything else is refused."""
    if len(args) != 2 or not isinstance(args[0], Proposal) or not isinstance(args[1], Callable):
        raise GbnRuntimeError("act(proposal, fn() { ... }) needs a proposal and its approved action", line)
    p, work = args
    bond = p.bond
    why = "Only work both partners approved can run under the bond"

    def refuse(what, reason=why):
        it.refuse(bond, f"act on proposal {p.id}: {what}", line, reason)

    status = p.status()
    if status != "approved":
        refuse(f"it is {status}, not approved by both")
    blocked = p.blocked_by()
    if blocked:
        need = Proposal(bond, p.entry_of(blocked[0]))
        refuse(f"it needs proposal {need.id}, which is {need.status()}")
    if not p.entry.get("action"):
        refuse("it names no action", "A proposal must name its action (options: {action: fn() { ... }}) "
               "so that only what was approved can run")
    if not isinstance(work, Function) or not work.source or action_hash(work) != p.entry["action"]:
        refuse("this is not the action both partners approved",
               "What was approved is exactly what runs; a changed action needs a new proposal")
    if p.expired():
        refuse(f"its approval expired on {p.entry['expires']}", "An expired approval is never stretched; propose again")
    counted = p.counted_uses()
    limit = p.entry.get("limit")
    if limit is not None and counted >= limit:
        refuse(f"its limit of {limit} uses is reached", "Propose again to allow more")
    if not p.standing and counted:
        refuse("it allowed one action and it was used",
               "A one-time approval is never reused; propose again, or approve a standing permission")
    # The start is written down before the work runs, so a crash cannot hide it.
    start = bond.journal.append("act", by="program", proposal=p.fingerprint, proposal_id=p.id,
                                use=len(p.actions()) + 1, state="started",
                                text=f"started the action of proposal {p.id}: {p.text}")
    try:
        result = it.call(work, list(copy.deepcopy(p.entry.get("args") or [])), line)
    except BaseException as e:
        bond.journal.append("act_end", by="program", proposal=p.fingerprint, execution=start["n"],
                            state="failed", error=str(e) or type(e).__name__,
                            text=f"the action of proposal {p.id} failed")
        raise
    bond.journal.append("act_end", by="program", proposal=p.fingerprint, execution=start["n"],
                        state="succeeded", text=f"the action of proposal {p.id} succeeded")
    return result


def _revoke(it, args, line):
    """Withdraw an approval. Partners are not identified yet, so this is recorded as a
    program-level revocation, not as a verified partner's withdrawal."""
    if len(args) != 1 or not isinstance(args[0], Proposal):
        raise GbnRuntimeError("revoke(proposal) needs a proposal", line)
    p = args[0]
    status = p.status()
    if status != "approved":
        raise GbnRuntimeError(f"proposal {p.id} is {status}; only an approved proposal can be revoked", line)
    p.bond.journal.append("revoke", by="program", verified=False, proposal=p.fingerprint, proposal_id=p.id,
                          text=f"the program revoked proposal {p.id} (which partner is not verified): {p.text}")
    return None


def _proposals(it, args, line, open_only=False):
    b = _bond(it, args, line, "unresolved" if open_only else "proposals")
    out = [Proposal(b, e) for e in b.journal.entries if e["kind"] == "proposal"]
    if open_only:
        out = [p for p in out if p.status() in ("pending", "disagreed", "deadlocked")]
    return out


def _objection(it, args, line):
    if not 1 <= len(args) <= 2 or not isinstance(args[0], str) or not args[0].strip():
        raise GbnRuntimeError("objection(reason, condition?) needs a reason", line)
    return Objection(args[0].strip(), args[1] if len(args) == 2 else None)


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
