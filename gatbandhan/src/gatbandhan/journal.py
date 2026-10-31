"""The bond's memory: an append-only, hash-chained journal.

Every entry stores the hash of the entry before it, so changing or deleting
an old entry breaks the chain and is caught the next time the journal is
opened. With a ``keep`` file the journal outlives the program run; without one
it lives in memory for the length of the run.

This makes tampering *evident*, not impossible: whoever owns the file can still
delete it. What the language guarantees is that no Gatbandhan program can
rewrite the bond's history, and that an edited file is refused, not trusted.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from .errors import GbnRuntimeError

GENESIS = "0" * 64


def _jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    from .values import show
    return show(v)


def _digest(prev, body):
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev + text).encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Journal:
    def __init__(self, path=None, clock=utc_now):
        self.path = path
        self.clock = clock
        self.entries = []
        if path and os.path.exists(path):
            self._load()

    def _load(self):
        prev = GENESIS
        with open(self.path, encoding="utf-8") as f:
            for i, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    raise GbnRuntimeError(f"bond journal {self.path} is damaged at entry {i}: not valid JSON")
                body = {k: v for k, v in entry.items() if k != "hash"}
                if entry.get("prev") != prev or entry.get("hash") != _digest(prev, body) or entry.get("n") != i:
                    raise GbnRuntimeError(
                        f"bond journal {self.path} was changed by hand at entry {i}; "
                        "a bond's history cannot be rewritten, so it is refused")
                prev = entry["hash"]
                self.entries.append(entry)

    @property
    def head(self):
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, kind, **fields):
        body = {"n": len(self.entries) + 1, "kind": kind, "at": self.clock(), "prev": self.head}
        for k, v in fields.items():
            if v is not None:
                body[k] = _jsonable(v)
        entry = dict(body, hash=_digest(body["prev"], body))
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
        self.entries.append(entry)
        return entry

    def find(self, kind):
        return [e for e in self.entries if e["kind"] == kind]

    def public_entries(self):
        return [{k: v for k, v in e.items() if k not in ("hash", "prev")} for e in self.entries]
