"""Построчный разбор Markdown-подмножества в блоки модели. Каждый блок помнит файл и строку."""
from __future__ import annotations

import re
import shlex

from .inline import InlineError, parse_inline
from .issues import Issues
from .model import (Figure, Formula, Heading, ListBlock, ListItem, Listing, Paragraph, Src, Table,
                    Text, Where)

ATTR_RE = re.compile(r"\{([^{}]*)\}\s*$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
FIG_RE = re.compile(r"^!\[(.*)\]\(([^)\s]+)\)\s*(\{[^{}]*\})?\s*$")
TABCAP_RE = re.compile(r"^(?:Таблица|Table)\s*:\s*(.*)$")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)\s*(.*)$")
MANUAL_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(?=\S)")


def parse_attrs(s: str) -> dict:
    """'{#fig:x width=80% caption="a b"}' -> {'id': 'fig:x', 'width': '80%', 'caption': 'a b'}"""
    s = s.strip()
    if s.startswith("{"):
        s = s[1:-1]
    out = {}
    try:
        toks = shlex.split(s, posix=True)
    except ValueError:
        toks = s.split()
    for t in toks:
        if t.startswith("#"):
            out["id"] = t[1:]
        elif t.startswith("."):
            out.setdefault("class", []).append(t[1:])
        elif "=" in t:
            k, v = t.split("=", 1)
            out[k] = v
        else:
            out[t] = True
    return out


def split_attrs(text: str):
    m = ATTR_RE.search(text)
    if m:
        return text[:m.start()].rstrip(), parse_attrs(m.group(0))
    return text, {}


def _label(attrs, kind, issues, src):
    ident = attrs.get("id", "")
    if not ident:
        return ""
    if not ident.startswith(kind + ":"):
        issues.err("LBL", f"метка «{ident}» должна начинаться с «{kind}:»", src,
                   f"например {{#{kind}:{ident.split(':')[-1]}}}")
        return ident.split(":")[-1]
    return ident[len(kind) + 1:]


def _inl(text, issues, src):
    try:
        return parse_inline(text)
    except InlineError as e:
        issues.err("INL", str(e), src)
        return [Text(text)]


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, i = [], [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if line[i] == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(line[i])
        i += 1
    cells.append("".join(cur).strip())
    return cells


def parse_markdown(text: str, file: str, issues: Issues) -> list:
    lines = text.splitlines()
    # вырезаем HTML-комментарии, сохраняя нумерацию строк
    joined = "\n".join(lines)
    joined = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), joined, flags=re.S)
    lines = joined.split("\n")

    blocks: list = []
    i, n = 0, len(lines)

    def src(k):
        return Src(file, k + 1)

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        # ---- заголовок
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            mm = MANUAL_NUM_RE.match(title)
            if mm and level <= 3:
                issues.fixed("B3", f"убран номер «{mm.group(1)}» из заголовка: номера ставит генератор", src(i))
                title = title[mm.end():]
            if title.endswith(".") and not title.endswith("..."):
                issues.fixed("B3", "убрана точка в конце заголовка", src(i))
                title = title[:-1]
            blocks.append(Heading(level, _inl(title, issues, src(i)), src(i)))
            i += 1
            continue

        # ---- листинг
        m = FENCE_RE.match(line)
        if m:
            fence = m.group(2)
            info = m.group(3).strip()
            lang, attrs = info, {}
            if "{" in info:
                lang, attrs = split_attrs(info)
                lang = lang.strip()
            start = i
            i += 1
            body = []
            while i < n and not lines[i].strip().startswith(fence[:3]):
                body.append(lines[i])
                i += 1
            if i >= n:
                issues.err("MD", "не закрыт блок кода ```", src(start))
            i += 1
            code = "\n".join(body).rstrip("\n").expandtabs(4)
            cap = attrs.get("caption", "")
            blocks.append(Listing(code, lang, _inl(cap, issues, src(start)) if cap else [],
                                  _label(attrs, "lst", issues, src(start)), src(start)))
            continue

        # ---- формула
        if line.strip().startswith("$$"):
            start = i
            s = line.strip()[2:]
            body = []
            if "$$" in s:
                tex, rest = s.split("$$", 1)
                body.append(tex)
                i += 1
            else:
                body.append(s)
                i += 1
                rest = ""
                while i < n:
                    if "$$" in lines[i]:
                        tex, rest = lines[i].split("$$", 1)
                        body.append(tex)
                        i += 1
                        break
                    body.append(lines[i])
                    i += 1
                else:
                    issues.err("MD", "не закрыта формула $$", src(start))
            _, attrs = split_attrs(rest) if rest.strip() else ("", {})
            tex = "\n".join(body).strip()
            blocks.append(Formula(tex, _label(attrs, "eq", issues, src(start)), src(start)))
            # пояснение «где …»
            k = i
            while k < n and not lines[k].strip():
                k += 1
            if k < n and re.match(r"^\s*где\b", lines[k]):
                wl = []
                wstart = k
                while k < n and lines[k].strip():
                    t = lines[k].strip()
                    if not wl:
                        t = re.sub(r"^где\s*:?\s*", "", t)
                    wl.append(_inl(t, issues, src(k)))
                    k += 1
                blocks.append(Where(wl, src(wstart)))
                i = k
            continue

        # ---- рисунок
        m = FIG_RE.match(line.strip())
        if m:
            attrs = parse_attrs(m.group(3)) if m.group(3) else {}
            width = None
            if "width" in attrs:
                w = str(attrs["width"]).rstrip("%")
                try:
                    width = float(w) / 100.0
                except ValueError:
                    issues.err("MD", f"не понял ширину рисунка «{attrs['width']}»", src(i), "пример: width=80%")
            blocks.append(Figure(m.group(2), _inl(m.group(1), issues, src(i)),
                                 _label(attrs, "fig", issues, src(i)), src(i), width))
            i += 1
            continue

        # ---- таблица (с подписью или без)
        m = TABCAP_RE.match(line.strip())
        if m or line.lstrip().startswith("|"):
            start = i
            cap_text, attrs = ("", {})
            if m:
                cap_text, attrs = split_attrs(m.group(1))
                i += 1
                while i < n and not lines[i].strip():
                    i += 1
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append((i, _split_row(lines[i])))
                i += 1
            if not rows:
                issues.err("MD", "после «Таблица: …» нет таблицы", src(start))
                continue
            def is_sep(cells):
                return all(re.fullmatch(r":?-{1,}:?", c.replace(" ", "")) for c in cells if c) and any(cells)
            sep_k = next((k for k, (_, cells) in enumerate(rows) if is_sep(cells)), None)
            if sep_k is None or sep_k == 0:
                issues.err("MD", "у таблицы нет строки-разделителя |---|---| после шапки", src(rows[0][0]))
                continue
            align = []
            for c in rows[sep_k][1]:
                c = c.replace(" ", "")
                align.append("center" if c.startswith(":") and c.endswith(":") else
                             "right" if c.endswith(":") else "left")
            ncol = len(rows[0][1])
            header = []
            for k, cells in rows[:sep_k]:
                if len(cells) != ncol:
                    issues.err("MD", f"в строке шапки {len(cells)} ячеек, а в первой строке {ncol}", src(k))
                    cells = (cells + [""] * ncol)[:ncol]
                header.append([_inl(c, issues, src(k)) for c in cells])
            body = []
            for k, cells in rows[sep_k + 1:]:
                if len(cells) != ncol:
                    issues.err("MD", f"в строке таблицы {len(cells)} ячеек, а в шапке {ncol}", src(k))
                    cells = (cells + [""] * ncol)[:ncol]
                body.append([_inl(c, issues, src(k)) for c in cells])
            t = Table(_inl(cap_text, issues, src(start)) if cap_text else [],
                      _label(attrs, "tbl", issues, src(start)), header, body, src(start), align,
                      numbered_header=attrs.get("header") == "numbered")
            blocks.append(t)
            continue

        # ---- список
        if LIST_RE.match(line):
            lb, i = _parse_list(lines, i, file, issues)
            blocks.append(lb)
            continue

        # ---- абзац
        start = i
        buf = []
        while i < n and lines[i].strip() and not (
                HEADING_RE.match(lines[i]) or FENCE_RE.match(lines[i]) or lines[i].strip().startswith("$$")
                or FIG_RE.match(lines[i].strip()) or lines[i].lstrip().startswith("|")
                or TABCAP_RE.match(lines[i].strip()) or (LIST_RE.match(lines[i]) and buf == [])):
            if buf and LIST_RE.match(lines[i]):
                break
            buf.append(lines[i].strip())
            i += 1
        if not buf:      # защита от зацикливания
            buf.append(lines[i].strip())
            i += 1
        blocks.append(Paragraph(_inl(" ".join(buf), issues, src(start)), src(start)))
    return blocks


def _parse_list(lines, i, file, issues):
    """Список с вложенностью по отступу."""
    n = len(lines)
    m = LIST_RE.match(lines[i])
    base_indent = len(m.group(1).expandtabs(4))
    style = _style(m.group(2))
    lb = ListBlock(style, [], Src(file, i + 1))
    while i < n:
        line = lines[i]
        if not line.strip():
            # пустая строка внутри списка допустима, если дальше снова пункт
            k = i + 1
            while k < n and not lines[k].strip():
                k += 1
            mk = LIST_RE.match(lines[k]) if k < n else None
            if mk:
                ind_k = len(mk.group(1).expandtabs(4))
                if ind_k > base_indent or (ind_k == base_indent and _style(mk.group(2)) == style):
                    i = k
                    continue
            break
        m = LIST_RE.match(line)
        if m:
            ind = len(m.group(1).expandtabs(4))
            if ind < base_indent:
                break
            if ind > base_indent:
                if not lb.items:
                    break
                child, i = _parse_list(lines, i, file, issues)
                child.depth = lb.depth + 1
                lb.items[-1].children.append(child)
                continue
            if _style(m.group(2)) != style:
                issues.warn("D3", "в одном списке смешаны разные маркеры", Src(file, i + 1),
                            "используй один вид: «-», «1.» или «1)»")
            item_lines = [m.group(3).strip()]
            start = i
            i += 1
            while i < n and lines[i].strip() and not LIST_RE.match(lines[i]) and not HEADING_RE.match(lines[i]):
                item_lines.append(lines[i].strip())
                i += 1
            lb.items.append(ListItem(_inl(" ".join(item_lines), issues, Src(file, start + 1)), Src(file, start + 1)))
            continue
        break
    return lb, i


def _style(marker: str) -> str:
    if marker in "-*+":
        return "dash"
    return "dot" if marker.endswith(".") else "paren"
