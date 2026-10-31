"""Error types raised by Gatbandhan."""


class GatbandhanError(Exception):
    """Base class for every error the language reports to the user."""

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


class GbnSyntaxError(GatbandhanError):
    pass


class GbnRuntimeError(GatbandhanError):
    pass
