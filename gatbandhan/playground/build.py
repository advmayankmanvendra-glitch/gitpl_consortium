"""Rebuild playground/index.html from template.html and the example programs.

    python playground/build.py

The playground shows the interactive examples in playground/examples/ next to
some of the language's own examples in ../examples/.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LANG_EXAMPLES = os.path.join(HERE, "..", "examples")

EXAMPLES = [
    ("first", "Your first bond", os.path.join(HERE, "examples", "first.gbn")),
    ("vows", "Vows can't be overwritten", os.path.join(LANG_EXAMPLES, "refused_overwrite.gbn")),
    ("bits", "Bits and gates", os.path.join(LANG_EXAMPLES, "bits.gbn")),
    ("remembers", "A bond that remembers", os.path.join(HERE, "examples", "remembers.gbn")),
    ("coalition", "A coalition votes", os.path.join(LANG_EXAMPLES, "coalition.gbn")),
    ("nested", "Coalitions of models", os.path.join(LANG_EXAMPLES, "nested.gbn")),
]


def build():
    data = []
    for ident, title, path in EXAMPLES:
        with open(path, encoding="utf-8") as f:
            data.append({"id": ident, "title": title, "source": f.read()})
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        page = f.read().replace("__EXAMPLES__", blob)
    return page


if __name__ == "__main__":
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(build())
    print("wrote playground/index.html")
