"""Command-line entry point: run a file, check its syntax, or start a REPL."""

import argparse
import sys

from . import __version__
from .errors import SutraError
from .interpreter import Interpreter, to_str
from .parser import parse


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sutra", description="Run Sutra programs.")
    parser.add_argument("file", nargs="?", help="a .sutra file to run (omit to start the REPL)")
    parser.add_argument("--model", help='default model, e.g. "mock" or "anthropic:claude-sonnet-5-5"')
    parser.add_argument("--check", action="store_true", help="only check the file's syntax")
    parser.add_argument("--version", action="version", version=f"sutra {__version__}")
    args = parser.parse_args(argv)

    if args.file is None:
        return repl(args.model)

    try:
        with open(args.file, encoding="utf-8") as fh:
            source = fh.read()
    except OSError as exc:
        print(f"sutra: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2

    try:
        if args.check:
            parse(source)
            print(f"{args.file}: ok")
            return 0
        Interpreter(model=args.model).run(source)
    except SutraError as exc:
        print(f"{args.file}: {type(exc).__name__.replace('Sutra', '')}: {exc}", file=sys.stderr)
        return 1
    return 0


def repl(model=None):
    interp = Interpreter(model=model)
    print(f"Sutra {__version__}. Blocks continue until braces balance; Ctrl-D to exit.")
    buffer = []
    while True:
        try:
            line = input("... " if buffer else ">>> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        buffer.append(line)
        source = "\n".join(buffer)
        if source.count("{") > source.count("}") or source.count('"""') % 2:
            continue
        buffer = []
        try:
            result = interp.run(source)
            if result is not None:
                print(to_str(result))
        except SutraError as exc:
            print(f"error: {exc}")
