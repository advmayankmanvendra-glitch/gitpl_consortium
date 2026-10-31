"""Error types shared by every stage of the Sutra pipeline."""


class SutraError(Exception):
    """Base class for all errors raised while lexing, parsing or running Sutra code."""

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        super().__init__(self.__str__())

    def __str__(self):
        if self.line is not None:
            return f"line {self.line}: {self.message}"
        return self.message


class SutraSyntaxError(SutraError):
    """Raised by the lexer or parser for malformed source code."""


class SutraRuntimeError(SutraError):
    """Raised by the interpreter while running a program."""


class ModelError(SutraRuntimeError):
    """Raised when a model backend fails or returns something unusable."""
