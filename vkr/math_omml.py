"""LaTeX → OMML (формулы Word) через pandoc, пакетно и с кэшем."""
from __future__ import annotations

import copy
import hashlib
import subprocess
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class MathCache:
    def __init__(self):
        self.cache: dict[str, etree._Element] = {}
        self.errors: dict[str, str] = {}

    def prepare(self, texs: list[str]):
        todo = [t for t in dict.fromkeys(texs) if t not in self.cache]
        if not todo:
            return
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "m.md"
            md.write_text("\n\n".join(f"$${t}$$" for t in todo) + "\n", encoding="utf-8")
            out = Path(d) / "m.docx"
            r = subprocess.run(["pandoc", str(md), "-f", "markdown", "-o", str(out)], capture_output=True, text=True)
            if r.returncode != 0:
                for t in todo:
                    self.errors[t] = r.stderr.strip()[:200]
                return
            with zipfile.ZipFile(out) as z:
                root = etree.fromstring(z.read("word/document.xml"))
        paras = root.findall(f".//{{{W_NS}}}body/{{{W_NS}}}p")
        maths = []
        for p in paras:
            om = p.find(f".//{{{M_NS}}}oMath")
            if om is not None:
                maths.append(om)
        if len(maths) != len(todo):
            # pandoc мог не разобрать какую-то формулу — переводим по одной
            for t in todo:
                self._single(t)
            return
        for t, om in zip(todo, maths):
            self.cache[t] = om

    def _single(self, t):
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "m.md"
            md.write_text(f"$${t}$$\n", encoding="utf-8")
            out = Path(d) / "m.docx"
            r = subprocess.run(["pandoc", str(md), "-o", str(out)], capture_output=True, text=True)
            if r.returncode == 0:
                with zipfile.ZipFile(out) as z:
                    root = etree.fromstring(z.read("word/document.xml"))
                om = root.find(f".//{{{M_NS}}}oMath")
                if om is not None:
                    self.cache[t] = om
                    return
            self.errors[t] = "pandoc не смог разобрать формулу"

    def get(self, tex: str):
        om = self.cache.get(tex)
        return copy.deepcopy(om) if om is not None else None
