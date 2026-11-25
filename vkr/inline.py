"""Разбор строки в inline-узлы: *курсив*, **жирный**, `код`, $формула$, [@cite], @ref, URL."""
from __future__ import annotations

import re

from .model import Bold, Cite, Code, Emph, Math, Ref, Text, Url

REF_RE = re.compile(r"@(fig|tbl|lst|eq|app):([A-Za-z0-9_\-]+)")
CITE_RE = re.compile(r"\[(@[^\[\]]+)\]")
CITE_ITEM_RE = re.compile(r"^\s*@([A-Za-z0-9_\-:.]*[A-Za-z0-9_\-])\s*(?:,\s*(.+?))?\s*$")
URL_RE = re.compile(r"https?://[^\s<>«»\"]+")


class InlineError(Exception):
    pass


def parse_inline(s: str) -> list:
    out: list = []
    buf: list[str] = []

    def flush():
        if buf:
            out.append(Text("".join(buf)))
            buf.clear()

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in "\\*`$[]@_#|":
            buf.append(s[i + 1])
            i += 2
            continue
        if c == "`":
            j = s.find("`", i + 1)
            if j > i:
                flush()
                out.append(Code(s[i + 1:j]))
                i = j + 1
                continue
        if c == "$" and not s.startswith("$$", i):
            j = i + 1
            while j < n and (s[j] != "$" or s[j - 1] == "\\"):
                j += 1
            if j < n and j > i + 1:
                flush()
                out.append(Math(s[i + 1:j].strip()))
                i = j + 1
                continue
        if c == "h" and (s.startswith("http://", i) or s.startswith("https://", i)):
            m = URL_RE.match(s, i)
            if m:
                url = m.group(0)
                while url and url[-1] in ".,;:)":
                    url = url[:-1]
                flush()
                out.append(Url(url))
                i += len(url)
                continue
        if c == "[":
            m = CITE_RE.match(s, i)
            if m:
                items = []
                for part in m.group(1).split(";"):
                    mm = CITE_ITEM_RE.match(part)
                    if not mm:
                        raise InlineError(f"не разобрана ссылка на источник: [{m.group(1)}]")
                    items.append((mm.group(1), mm.group(2)))
                flush()
                out.append(Cite(items))
                i = m.end()
                continue
        if c == "@":
            m = REF_RE.match(s, i)
            if m:
                flush()
                out.append(Ref(m.group(1), m.group(2)))
                i = m.end()
                continue
        if s.startswith("**", i):
            j = s.find("**", i + 2)
            if j > i + 2:
                flush()
                out.append(Bold(parse_inline(s[i + 2:j])))
                i = j + 2
                continue
        if c == "*" and i + 1 < n and s[i + 1] not in " *":
            j = i + 1
            while j < n and not (s[j] == "*" and s[j - 1] != " " and not s.startswith("**", j)):
                j += 1
            if j < n:
                flush()
                out.append(Emph(parse_inline(s[i + 1:j])))
                i = j + 1
                continue
        buf.append(c)
        i += 1
    flush()
    return out
