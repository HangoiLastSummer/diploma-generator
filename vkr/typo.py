"""Типографика: тире, кавычки, неразрывные пробелы, пунктуация перечислений.

Работает на уровне модели (при сборке) и на уровне исходника (vkr fix) одними и теми же функциями.
"""
from __future__ import annotations

import re

from .model import (Bold, Code, Emph, Heading, ListBlock, Math, Paragraph, Text, Url, Figure,
                    Table, Listing, Where, Cite, Ref)

NBSP = " "

SHORT_BODY = r"в|во|и|к|ко|с|со|о|об|у|а|не|ни|на|по|за|из|от|до|но|же|ли|бы"
SHORT_HEAD = SHORT_BODY + r"|для|при|без|под|над|про|или|как|что|его|их|это|обо|изо"
UNITS = (r"ГБ|МБ|КБ|ТБ|Гбит|Мбит|Гб|Мб|км|м|см|мм|мкм|нм|кг|г|т|с|мс|мкс|нс|мин|ч|сут|"
         r"руб\.?|тыс\.|млн|млрд|%|°C|°|Гц|кГц|МГц|ГГц|Вт|кВт|В|А|Ом|бит|байт|шт\.|стр\.|с\.|p\.|лет|год|года|г\.|гг\.|"
         r"ядер|ядра|потоков|пикс\.|px|dpi|раз")


def _dashes(s: str) -> str:
    s = s.replace(" -- ", " – ").replace("—", "–")
    s = re.sub(r"(?<=\S) - (?=\S)", " – ", s)
    s = re.sub(r"(?<=\S) -(?=\s)", " –", s)      # «слово -\n»
    s = re.sub(r"(?<=\s)-(?= )", "–", s)        # « - » в середине после пробела
    s = re.sub(r"\s+–\s*", " – ", s) if " –" in s or "– " in s else s
    return s


def _spaces(s: str) -> str:
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" +([,.;:!?)»])", r"\1", s)
    s = re.sub(r"([(«]) +", r"\1", s)
    s = s.replace("...", "…")
    return s


def _nbsp(s: str, heading: bool) -> str:
    words = SHORT_HEAD if heading else r"в|и|к|с|о|у|а|не|ни"
    s = re.sub(rf"(?<![\w\-])({words}) (?=\S)", lambda m: m.group(1) + NBSP, s, flags=re.I)
    s = re.sub(rf"(\d) ({UNITS})(?![\wа-яё])", lambda m: m.group(1) + NBSP + m.group(2), s)
    s = re.sub(r"№ (?=\d)", "№" + NBSP, s)
    s = re.sub(r"\bт\. ?([едпн])\.", lambda m: "т." + NBSP + m.group(1) + ".", s)
    s = re.sub(r"\b(и|и др\.|и т\.) (д|п|т)\.", lambda m: m.group(1) + NBSP + m.group(2) + ".", s)
    # инициалы: «А.В. Кирсанова», «Кирсанова А.В.»
    s = re.sub(r"\b([А-ЯЁA-Z]\.) ?([А-ЯЁA-Z]\.) ([А-ЯЁ][а-яё]+)", lambda m: m.group(1) + m.group(2) + NBSP + m.group(3), s)
    s = re.sub(r"([А-ЯЁ][а-яё]+) ([А-ЯЁ]\.) ?([А-ЯЁ]\.)", lambda m: m.group(1) + NBSP + m.group(2) + m.group(3), s)
    return s


def fix_text(s: str, heading: bool = False) -> str:
    return _nbsp(_spaces(_dashes(s)), heading)


# ---------- кавычки через границы inline-узлов ----------

def _texts_in_order(inlines):
    for x in inlines:
        if isinstance(x, Text):
            yield x
        elif isinstance(x, (Emph, Bold)):
            yield from _texts_in_order(x.children)


def _visible_seq(inlines):
    """Последовательность (node|None, text) для определения соседних символов вокруг кавычек."""
    for x in inlines:
        if isinstance(x, Text):
            yield x, x.s
        elif isinstance(x, (Emph, Bold)):
            yield from _visible_seq(x.children)
        elif isinstance(x, (Code, Url)):
            yield None, x.s
        elif isinstance(x, Math):
            yield None, "x"
        elif isinstance(x, (Ref, Cite)):
            yield None, "0"


def fix_quotes(inlines) -> int:
    seq = list(_visible_seq(inlines))
    full = "".join(t for _, t in seq)
    if '"' not in full and "“" not in full and "”" not in full and "„" not in full:
        return 0
    chars = list(full)
    depth = 0
    changed = 0
    for i, ch in enumerate(chars):
        if ch not in '"“”':
            if ch == "«":
                depth += 1
            elif ch == "»":
                depth = max(0, depth - 1)
            continue
        prev = chars[i - 1] if i > 0 else " "
        opening = prev.isspace() or prev in "([{–-/" + NBSP or i == 0
        if ch == "“" and not opening and depth == 0:
            opening = True
        if opening:
            chars[i] = "«" if depth == 0 else "„"
            depth += 1
        else:
            depth = max(0, depth - 1)
            chars[i] = "»" if depth == 0 else "“"
        changed += 1
    out = "".join(chars)
    pos = 0
    for node, t in seq:
        if node is not None:
            node.s = out[pos:pos + len(t)]
        pos += len(t)
    return changed


def apply_inlines(inlines, heading=False) -> int:
    changed = fix_quotes(inlines)
    for t in _texts_in_order(inlines):
        new = fix_text(t.s, heading)
        if new != t.s:
            # считаем «видимые» изменения: тире, кавычки, пробелы; неразрывные пробелы не шумим
            if new.replace(NBSP, " ") != t.s.replace(NBSP, " "):
                changed += 1
            t.s = new
    return changed


# ---------- перечисления ----------

def _first_text(inlines):
    for x in inlines:
        if isinstance(x, Text):
            return x if x.s.strip() else None
        if isinstance(x, (Emph, Bold)):
            return _first_text(x.children)
        return None
    return None


def _last_text(inlines):
    if not inlines:
        return None
    x = inlines[-1]
    if isinstance(x, Text):
        return x
    if isinstance(x, (Emph, Bold)):
        # пунктуацию ставим снаружи выделения
        return None
    return None


def _should_lower(word: str) -> bool:
    if not word or not re.match(r"[А-ЯЁ]", word):
        return False
    core = re.match(r"[А-ЯЁа-яё]+", word).group(0)
    return len(core) == 1 or core[1:].islower()


def fix_list(lb: ListBlock, is_last_scope: bool = True, src_issues=None) -> int:
    """Пункты: «-» и «1)» — со строчной и «;», последний «.»; «1.» — с прописной и «.»."""
    changed = 0
    for k, it in enumerate(lb.items):
        last_here = k == len(lb.items) - 1
        has_children = bool(it.children)
        ft = _first_text(it.inlines)
        if ft is not None:
            m = re.match(r"(\s*)(\S+)", ft.s)
            if m:
                w = m.group(2)
                if lb.style == "dot":
                    if w[0].islower():
                        ft.s = ft.s[:m.start(2)] + w[0].upper() + ft.s[m.start(2) + 1:]
                        changed += 1
                elif _should_lower(w):
                    ft.s = ft.s[:m.start(2)] + w[0].lower() + ft.s[m.start(2) + 1:]
                    changed += 1
        if has_children:
            want = ":"
        elif lb.style == "dot":
            want = "."
        else:
            want = "." if (last_here and is_last_scope) else ";"
        lt = _last_text(it.inlines)
        if lt is None:
            it.inlines.append(Text(want))
            changed += 1
        else:
            s = lt.s.rstrip()
            if s.endswith(("?", "!", "…")) and not has_children:
                pass
            else:
                core = s.rstrip(".;,:")
                if core + want != s:
                    lt.s = core + want
                    changed += 1
        for ch in it.children:
            changed += fix_list(ch, is_last_scope and last_here, src_issues)
    return changed


def apply_block(b) -> int:
    if isinstance(b, Heading):
        return apply_inlines(b.inlines, heading=True)
    if isinstance(b, Paragraph):
        return apply_inlines(b.inlines)
    if isinstance(b, ListBlock):
        n = 0
        def rec(lb):
            nonlocal n
            for it in lb.items:
                n += apply_inlines(it.inlines)
                for ch in it.children:
                    rec(ch)
        rec(b)
        return n + fix_list(b)
    if isinstance(b, (Figure, Listing)):
        return apply_inlines(b.caption, heading=True)
    if isinstance(b, Table):
        n = apply_inlines(b.caption, heading=True)
        for row in b.header + b.rows:
            for cell in row:
                n += apply_inlines(cell)
        return n
    if isinstance(b, Where):
        return sum(apply_inlines(ln) for ln in b.lines)
    return 0
