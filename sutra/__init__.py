"""Sutra: a small programming language where prompts, models, typed outputs,
tools and agents are part of the syntax."""

from .errors import ModelError, SutraError, SutraRuntimeError, SutraSyntaxError
from .interpreter import Interpreter, run_source
from .models import AnthropicModel, MockModel, make_model
from .parser import parse

__version__ = "0.1.0"

__all__ = [
    "AnthropicModel",
    "Interpreter",
    "MockModel",
    "ModelError",
    "SutraError",
    "SutraRuntimeError",
    "SutraSyntaxError",
    "make_model",
    "parse",
    "run_source",
]
