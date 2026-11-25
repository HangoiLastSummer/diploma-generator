from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .model import Src

ERROR, WARNING, FIXED = "error", "warning", "fixed"


@dataclass
class Issue:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0
    hint: str = ""
    page: Optional[int] = None

    def to_dict(self):
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in ("", None, 0) or k in ("rule", "severity", "message")}

    def loc(self) -> str:
        s = f"{self.file}:{self.line}" if self.file else ""
        if self.page:
            s = f"{s} (стр. {self.page})" if s else f"стр. {self.page}"
        return s


class Issues(list):
    def add(self, rule, severity, message, src: Optional[Src] = None, hint="", page=None):
        self.append(Issue(rule, severity, message, src.file if src else "", src.line if src else 0, hint, page))

    def err(self, rule, message, src=None, hint=""):
        self.add(rule, ERROR, message, src, hint)

    def warn(self, rule, message, src=None, hint="", page=None):
        self.add(rule, WARNING, message, src, hint, page)

    def fixed(self, rule, message, src=None):
        self.add(rule, FIXED, message, src)

    @property
    def errors(self):
        return [i for i in self if i.severity == ERROR]

    @property
    def warnings(self):
        return [i for i in self if i.severity == WARNING]
