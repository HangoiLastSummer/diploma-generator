"""vkr fix: безопасные правки прямо в .md (тире, кавычки, пробелы, пунктуация перечислений).

Неразрывные пробелы в исходник не пишутся — они невидимы в редакторе; их ставит сборка.
"""
from __future__ import annotations

import re

from .parser import LIST_RE, FENCE_RE
from .typo import _dashes, _should_lower

PROTECT = re.compile(r"`[^`]*`|\$[^$]+\$|https?://\S+|\[@[^\]]+\]|@(?:fig|tbl|lst|eq|app):[\w\-]+|\{[^{}]*\}|!\[[^\]]*\]\([^)]*\)|<!--.*?-->")


def _quotes_str(s: str) -> str:
    out, depth = [], 0
    for i, ch in enumerate(s):
        if ch == "«":
            depth += 1
        elif ch == "»":
            depth = max(0, depth - 1)
        if ch not in '"“”':
            out.append(ch)
            continue
        prev = s[i - 1] if i else " "
        if prev.isspace() or prev in "([{–-/\x00" or i == 0:
            out.append("«" if depth == 0 else "„")
            depth += 1
        else:
            depth = max(0, depth - 1)
            out.append("»" if depth == 0 else "“")
    return "".join(out)


def _fix_text(s: str) -> str:
    keep = []

    def stash(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"
    t = PROTECT.sub(stash, s)
    t = _dashes(t)
    t = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", t)
    t = _quotes_str(t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)
    return t


def fix_markdown(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    out = list(lines)
    in_code = False
    in_comment = False
    changes = 0
    i = 0
    items = []          # (start, end, indent, style)
    while i < len(lines):
        ln = lines[i]
        if FENCE_RE.match(ln):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        if "<!--" in ln and "-->" not in ln:
            in_comment = True
        if in_comment:
            if "-->" in ln:
                in_comment = False
            i += 1
            continue
        stripped = ln.strip()
        if (stripped.startswith("|") or stripped.startswith("$$") or stripped.startswith("![")
                or re.match(r"^#{1,4}\s", stripped)):
            if re.match(r"^#{1,4}\s", stripped) or stripped.startswith("|"):
                new = _fix_text(ln)
                if new != ln:
                    out[i] = new
                    changes += 1
            i += 1
            continue
        new = _fix_text(ln)
        if new != ln:
            out[i] = new
            changes += 1
        m = LIST_RE.match(out[i])
        if m:
            start = i
            j = i + 1
            while j < len(lines) and lines[j].strip() and not LIST_RE.match(lines[j]) and not lines[j].startswith("#"):
                nj = _fix_text(lines[j])
                if nj != lines[j]:
                    out[j] = nj
                    changes += 1
                j += 1
            marker = m.group(2)
            style = "dash" if marker in "-*+" else ("dot" if marker.endswith(".") else "paren")
            items.append((start, j - 1, len(m.group(1).expandtabs(4)), style))
            i = j
            continue
        i += 1

    # пунктуация перечислений: группы подряд идущих пунктов
    groups, cur = [], []
    for it in items:
        if cur and (it[0] - cur[-1][1] > 2 or (it[2] == cur[-1][2] and it[3] != cur[-1][3])):
            groups.append(cur)
            cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    for g in groups:
        for k, (s, e, ind, style) in enumerate(g):
            nxt = g[k + 1] if k + 1 < len(g) else None
            has_children = nxt is not None and nxt[2] > ind
            # последний пункт всей группы или последний на своём уровне перед возвратом выше
            last_in_group = nxt is None
            m = LIST_RE.match(out[s])
            body = m.group(3)
            w = body.split(" ", 1)[0] if body else ""
            new_body = body
            if style == "dot":
                if w and w[0].islower():
                    new_body = w[0].upper() + body[1:]
            elif _should_lower(w):
                new_body = w[0].lower() + body[1:]
            if new_body != body:
                out[s] = out[s][:m.start(3)] + new_body
                changes += 1
            want = ":" if has_children else ("." if (style == "dot" or last_in_group) else ";")
            tail = out[e].rstrip()
            if tail.endswith(("?", "!", "…")) and not has_children:
                continue
            core = tail.rstrip(".;,:")
            if core + want != tail:
                out[e] = core + want
                changes += 1
    return "\n".join(out), changes
