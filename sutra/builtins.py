"""Built-in functions available in every Sutra program.

Each builtin receives the interpreter as its first argument.
"""

import json
import os

from .errors import SutraRuntimeError
from .models import MockModel, make_model


def _interp_helpers():
    # Imported lazily to avoid a circular import with interpreter.py.
    from . import interpreter

    return interpreter


def _print(interp, *args, sep=" "):
    to_str = _interp_helpers().to_str
    interp.write(sep.join(to_str(a) for a in args))


def _len(interp, value):
    if isinstance(value, (str, list, dict)):
        return len(value)
    raise SutraRuntimeError(f"len() needs a str, list or map, not {_interp_helpers().type_name(value)}")


def _str(interp, value):
    return _interp_helpers().to_str(value)


def _num(interp, value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        return float(text)


def _int(interp, value):
    return int(_num(interp, value))


def _range(interp, start, stop=None, step=1):
    if stop is None:
        start, stop = 0, start
    return list(range(int(start), int(stop), int(step)))


def _push(interp, items, value):
    items.append(value)
    return items


def _pop(interp, items):
    if not items:
        raise SutraRuntimeError("pop() from an empty list")
    return items.pop()


def _join(interp, items, sep=""):
    to_str = _interp_helpers().to_str
    return sep.join(to_str(i) for i in items)


def _split(interp, text, sep=None):
    return text.split(sep) if sep is not None else text.split()


def _keys(interp, mapping):
    return list(mapping.keys())


def _values(interp, mapping):
    return list(mapping.values())


def _json(interp, value, indent=None):
    helpers = _interp_helpers()
    return json.dumps(helpers.to_jsonable(value), ensure_ascii=False, indent=indent)


def _parse_json(interp, text):
    return _interp_helpers().parse_json_loose(text)


def _type_of(interp, value):
    return _interp_helpers().type_name(value)


def _model(interp, spec, options=None):
    return make_model(spec, options)


def _mock(interp, script=None):
    return MockModel(script)


def _assert(interp, condition, message="assertion failed"):
    if not _interp_helpers().truthy(condition):
        raise SutraRuntimeError(_interp_helpers().to_str(message))


def _read(interp, path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _env(interp, name, default=None):
    return os.environ.get(name, default)


def _slice(interp, value, start, end=None):
    return value[int(start) : (int(end) if end is not None else None)]


def _sort(interp, items, key=None):
    if key is None:
        return sorted(items)
    return sorted(items, key=lambda item: interp.call(key, [item], {}))


def _map(interp, items, fn):
    return [interp.call(fn, [item], {}) for item in items]


def _filter(interp, items, fn):
    truthy = _interp_helpers().truthy
    return [item for item in items if truthy(interp.call(fn, [item], {}))]


def _contains(interp, container, item):
    return item in container


def _words(interp, text):
    return len(str(text).split())


BUILTINS = {
    "print": _print,
    "len": _len,
    "str": _str,
    "num": _num,
    "int": _int,
    "range": _range,
    "push": _push,
    "pop": _pop,
    "join": _join,
    "split": _split,
    "upper": lambda interp, s: s.upper(),
    "lower": lambda interp, s: s.lower(),
    "trim": lambda interp, s: s.strip(),
    "replace": lambda interp, s, old, new: s.replace(old, new),
    "starts_with": lambda interp, s, prefix: s.startswith(prefix),
    "ends_with": lambda interp, s, suffix: s.endswith(suffix),
    "keys": _keys,
    "values": _values,
    "json": _json,
    "parse_json": _parse_json,
    "type_of": _type_of,
    "model": _model,
    "mock": _mock,
    "assert": _assert,
    "read": _read,
    "env": _env,
    "slice": _slice,
    "sort": _sort,
    "map": _map,
    "filter": _filter,
    "contains": _contains,
    "words": _words,
}
