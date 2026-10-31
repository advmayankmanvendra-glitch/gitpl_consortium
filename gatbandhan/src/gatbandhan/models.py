"""Where answers from outside the program come from: models and the human.

``consult(model, text)`` asks a model. Models scripted with ``script`` answer
offline, which is what tests and examples use. A model whose name starts with
``claude`` is called through the Anthropic Messages API when ANTHROPIC_API_KEY
is set (standard library only; not exercised by the test suite).
"""

import json
import os
import sys
import urllib.error
import urllib.request

from .errors import GbnRuntimeError

API_URL = "https://api.anthropic.com/v1/messages"


class Models:
    def __init__(self):
        self.scripted = {}

    def script(self, name, replies):
        self.scripted[name] = list(replies)

    def consult(self, name, text, system=None, line=None):
        if name in self.scripted:
            queue = self.scripted[name]
            if not queue:
                raise GbnRuntimeError(f"model '{name}' has no scripted replies left", line)
            return queue.pop(0)
        if name.startswith("claude") and os.environ.get("ANTHROPIC_API_KEY"):
            return self._anthropic(name, text, system, line)
        raise GbnRuntimeError(
            f"no model named '{name}': script it with script(\"{name}\", [...]) "
            "or set ANTHROPIC_API_KEY to use a Claude model", line)

    def _anthropic(self, name, text, system, line):
        body = {"model": name, "max_tokens": 1024, "messages": [{"role": "user", "content": text}]}
        if system:
            body["system"] = system
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                     "x-api-key": os.environ["ANTHROPIC_API_KEY"]})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise GbnRuntimeError(f"model '{name}' call failed: HTTP {e.code} {e.read()[:300]!r}", line)
        except urllib.error.URLError as e:
            raise GbnRuntimeError(f"model '{name}' call failed: {e.reason}", line)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class Human:
    """The human partner. Answers come from the terminal, or from a script in tests.

    A missing answer (end of input, or a blank line) is ``None``: silence is
    never taken as consent.
    """

    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.scripted = None

    def script(self, replies):
        self.scripted = list(replies)

    def line(self, prompt):
        if self.scripted is not None:
            if not self.scripted:
                return None
            reply = self.scripted.pop(0)
            return reply
        self.stdout.write(prompt)
        self.stdout.flush()
        raw = self.stdin.readline()
        if not raw:
            return None
        raw = raw.rstrip("\n")
        return raw if raw.strip() else None

    def answer(self, name, question):
        """Return (answer, feeling); answer is None when the human said nothing."""
        reply = self.line(f"{name}, {question}\n> ")
        if isinstance(reply, dict):
            return reply.get("answer"), reply.get("feeling")
        if reply is None:
            return None, None
        if self.scripted is not None:
            return reply, None
        feeling = self.line("How do you feel about it? (Enter to skip)\n> ")
        return reply, feeling
