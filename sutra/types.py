"""Runtime types used by ``ask ... as T`` and typed tool parameters.

Every type can (1) describe itself as JSON Schema, which is sent to models,
(2) validate and coerce a parsed JSON value, and (3) produce a placeholder
example value, which the offline mock model uses.
"""

from .errors import SutraRuntimeError


class ValidationError(Exception):
    pass


class SType:
    name = "any"

    def schema(self):
        return {}

    def validate(self, value, path="value"):
        return value

    def example(self):
        return None

    def __repr__(self):
        return self.name


class AnyType(SType):
    name = "any"

    def example(self):
        return "example"


class StrType(SType):
    name = "str"

    def schema(self):
        return {"type": "string"}

    def validate(self, value, path="value"):
        if not isinstance(value, str):
            raise ValidationError(f"{path} should be a string")
        return value

    def example(self):
        return "example"


class NumType(SType):
    name = "num"

    def schema(self):
        return {"type": "number"}

    def validate(self, value, path="value"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if isinstance(value, str):
                try:
                    return int(value) if value.strip().lstrip("-").isdigit() else float(value)
                except ValueError:
                    pass
            raise ValidationError(f"{path} should be a number")
        return value

    def example(self):
        return 0


class BoolType(SType):
    name = "bool"

    def schema(self):
        return {"type": "boolean"}

    def validate(self, value, path="value"):
        if not isinstance(value, bool):
            raise ValidationError(f"{path} should be true or false")
        return value

    def example(self):
        return False


class ListType(SType):
    def __init__(self, elem):
        self.elem = elem

    @property
    def name(self):
        return f"[{self.elem!r}]"

    def schema(self):
        return {"type": "array", "items": self.elem.schema()}

    def validate(self, value, path="value"):
        if not isinstance(value, list):
            raise ValidationError(f"{path} should be a list")
        return [self.elem.validate(v, f"{path}[{i}]") for i, v in enumerate(value)]

    def example(self):
        return [self.elem.example()]


class ObjectType(SType):
    def __init__(self, fields):
        self.fields = fields  # list of (name, type, optional)

    @property
    def name(self):
        inner = ", ".join(f"{n}{'?' if o else ''}: {t!r}" for n, t, o in self.fields)
        return "{" + inner + "}"

    def schema(self):
        return {
            "type": "object",
            "properties": {n: t.schema() for n, t, _ in self.fields},
            "required": [n for n, _, o in self.fields if not o],
            "additionalProperties": False,
        }

    def validate(self, value, path="value"):
        if not isinstance(value, dict):
            raise ValidationError(f"{path} should be an object")
        out = {}
        for fname, ftype, optional in self.fields:
            if fname not in value or value[fname] is None:
                if optional:
                    out[fname] = None
                    continue
                raise ValidationError(f"{path} is missing field '{fname}'")
            out[fname] = ftype.validate(value[fname], f"{path}.{fname}")
        return out

    def example(self):
        return {n: t.example() for n, t, _ in self.fields}


class EnumType(SType):
    def __init__(self, values):
        self.values = values

    @property
    def name(self):
        return " | ".join(f'"{v}"' for v in self.values)

    def schema(self):
        return {"type": "string", "enum": list(self.values)}

    def validate(self, value, path="value"):
        if isinstance(value, str):
            cleaned = value.strip().strip("\"'").strip()
            for option in self.values:
                if cleaned.lower() == option.lower():
                    return option
        raise ValidationError(f"{path} should be one of {', '.join(self.values)}")

    def example(self):
        return self.values[0]


class NamedType(SType):
    """A user-declared ``type Name = ...`` alias."""

    def __init__(self, name, inner):
        self._name = name
        self.inner = inner

    @property
    def name(self):
        return self._name

    def schema(self):
        return self.inner.schema()

    def validate(self, value, path="value"):
        return self.inner.validate(value, path)

    def example(self):
        return self.inner.example()


BUILTIN_TYPES = {
    "any": AnyType(),
    "str": StrType(),
    "string": StrType(),
    "num": NumType(),
    "number": NumType(),
    "int": NumType(),
    "bool": BoolType(),
}


def build_type(node, lookup):
    """Turn a type AST node into an SType. ``lookup(name)`` resolves user types."""
    kind = node.kind
    if kind == "TName":
        if node.name in BUILTIN_TYPES:
            return BUILTIN_TYPES[node.name]
        found = lookup(node.name)
        if not isinstance(found, SType):
            raise SutraRuntimeError(f"'{node.name}' is not a type", node.line)
        return found
    if kind == "TLiteral":
        return EnumType([node.value])
    if kind == "TEnum":
        return EnumType(node.values)
    if kind == "TList":
        return ListType(build_type(node.elem, lookup))
    if kind == "TObject":
        return ObjectType([(n, build_type(t, lookup), o) for n, t, o in node.fields])
    raise SutraRuntimeError(f"unknown type node {kind}", node.line)
