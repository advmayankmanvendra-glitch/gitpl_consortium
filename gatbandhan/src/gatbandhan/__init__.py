"""Gatbandhan: a language for a bond between a human and an AI."""

from .builtins import VERSION as __version__
from .errors import GatbandhanError, GbnRuntimeError, GbnSyntaxError
from .interpreter import BondError, Interpreter
from .parser import parse


def run(src, **kwargs):
    """Run Gatbandhan source and return the interpreter (handy in tests)."""
    it = Interpreter(**kwargs)
    it.run(src)
    return it


__all__ = ["Interpreter", "parse", "run", "GatbandhanError", "GbnSyntaxError",
           "GbnRuntimeError", "BondError", "__version__"]
