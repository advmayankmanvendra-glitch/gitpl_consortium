"""Command line: ``gatbandhan file.gbn`` runs a program; no file starts a REPL."""

import argparse
import os
import sys

from .builtins import VERSION
from .errors import GatbandhanError
from .interpreter import Interpreter


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gatbandhan", description="Run a Gatbandhan program.")
    ap.add_argument("file", nargs="?", help="a .gbn file; leave out for an interactive prompt")
    ap.add_argument("--version", action="version", version=f"gatbandhan {VERSION}")
    args = ap.parse_args(argv)

    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print(f"gatbandhan: cannot read {args.file}: {e.strerror}", file=sys.stderr)
            return 2
        it = Interpreter(base_dir=os.path.dirname(os.path.abspath(args.file)))
        try:
            it.run(src)
        except GatbandhanError as e:
            print(f"{args.file}: {e}", file=sys.stderr)
            return 1
        return 0
    return repl()


def repl():
    print(f"Gatbandhan {VERSION}. Each complete line runs; open braces continue. Ctrl-D quits.")
    it = Interpreter()
    buf = []
    while True:
        try:
            line = input("... " if buf else "gbn> ")
        except EOFError:
            print()
            return 0
        buf.append(line)
        if _open_braces("\n".join(buf)):
            continue
        src = "\n".join(buf)
        buf = []
        if not src.strip():
            continue
        try:
            it.run(src)
        except GatbandhanError as e:
            print(f"error: {e}")


def _open_braces(src):
    depth, quote = 0, False
    for i, c in enumerate(src):
        if c == '"' and (i == 0 or src[i - 1] != "\\"):
            quote = not quote
        elif not quote and c == "{":
            depth += 1
        elif not quote and c == "}":
            depth -= 1
    return depth > 0
