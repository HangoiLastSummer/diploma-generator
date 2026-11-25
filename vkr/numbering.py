"""Нумерация глав, подразделов, рисунков, таблиц, листингов, формул, приложений и источников."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Cite, Figure, Formula, Heading, Listing, Part, Ref, Table, plain, walk_inlines, block_items

SPECIAL_UG = {"введение": "ВВЕДЕНИЕ", "заключение": "ЗАКЛЮЧЕНИЕ"}


@dataclass
class Numbering:
    labels: dict = field(default_factory=dict)       # (kind, label) -> number str
    label_src: dict = field(default_factory=dict)    # (kind, label) -> Src
    objects: dict = field(default_factory=dict)      # (kind, label) -> block
    counts: dict = field(default_factory=dict)       # kind -> total
    cite_order: list = field(default_factory=list)   # ключи в порядке первого упоминания
    cite_num: dict = field(default_factory=dict)     # key -> N
    first_ref_pos: dict = field(default_factory=dict)  # (kind,label) -> порядковый номер появления в тексте


def number_project(pr, issues) -> Numbering:
    nb = Numbering()
    seq = 0

    def reg(kind, label, num, block):
        if not label:
            return
        key = (kind, label)
        if key in nb.labels:
            issues.err("LBL", f"метка @{kind}:{label} уже использована ({nb.label_src[key]})", block.src)
            return
        nb.labels[key] = num
        nb.label_src[key] = block.src
        nb.objects[key] = block

    # ---- основная часть
    ch = 0
    sec = [0, 0]
    cnt = {}
    parts = [p for p in (pr.intro, pr.body, pr.conclusion) if p]
    for part in parts:
        for b in part.blocks:
            if isinstance(b, Heading):
                if part.role != "body":
                    if b.level <= 3:
                        issues.err("B1", "во введении и заключении не должно быть нумеруемых заголовков", b.src,
                                   "используй #### для псевдозаголовка или убери заголовок")
                    continue
                if b.level == 1:
                    ch += 1
                    sec = [0, 0]
                    cnt = {}
                    b.number = str(ch)
                elif b.level == 2:
                    if ch == 0:
                        issues.err("B2", "подраздел до первой главы (нет заголовка #)", b.src)
                    sec = [sec[0] + 1, 0]
                    b.number = f"{ch}.{sec[0]}"
                elif b.level == 3:
                    sec[1] += 1
                    b.number = f"{ch}.{sec[0]}.{sec[1]}"
                continue
            prefix = str(ch) if part.role == "body" else None
            _number_obj(b, prefix, cnt, reg, issues, part)

    # ---- приложения
    for app in pr.appendices:
        reg("app", app.label, app.letter, _AppStub(app))
        cnt = {}
        ugch = 0
        ugsec = [0, 0]
        for b in app.blocks:
            if isinstance(b, Heading):
                if app.kind == "user-guide" and b.level <= 3:
                    t = plain(b.inlines).strip().lower()
                    if b.level == 1 and t in SPECIAL_UG:
                        b.kind = "special"
                        continue
                    if b.level == 1:
                        ugch += 1
                        ugsec = [0, 0]
                        b.number = str(ugch)
                    elif b.level == 2:
                        ugsec = [ugsec[0] + 1, 0]
                        b.number = f"{ugch}.{ugsec[0]}"
                    else:
                        ugsec[1] += 1
                        b.number = f"{ugch}.{ugsec[0]}.{ugsec[1]}"
                elif b.level <= 3:
                    # в обычном приложении заголовки — без номера
                    b.kind = "appendix-sub"
                continue
            _number_obj(b, app.letter, cnt, reg, issues, app)

    # единственный рисунок/формула — без номера (М 3.2); таблицы нумеруются всегда (решение автора).
    # Список настраивается: single_unnumbered: [fig, eq] в diploma.yaml
    single = pr.cfg.get("single_unnumbered", ["fig", "eq"]) or []
    for kind, cls in (("fig", Figure), ("tbl", Table), ("eq", Formula)):
        if kind not in single:
            nb.counts[kind] = sum(1 for p in parts + pr.appendices for b in p.blocks if isinstance(b, cls))
            continue
        objs = [b for p in parts + pr.appendices for b in p.blocks if isinstance(b, cls)]
        nb.counts[kind] = len(objs)
        if len(objs) == 1 and parts and objs[0] in [b for p in parts for b in p.blocks]:
            objs[0].number = ""
            for k, v in list(nb.objects.items()):
                if v is objs[0]:
                    nb.labels[k] = ""

    # ---- ссылки: порядок появления, цитирования
    pos = 0
    for part in parts + pr.appendices:
        for blk, inl in block_items(part.blocks):
            for x in walk_inlines(inl):
                if isinstance(x, Ref):
                    pos += 1
                    nb.first_ref_pos.setdefault((x.kind, x.label), (pos, getattr(blk, "src", None)))
                elif isinstance(x, Cite):
                    for key, _ in x.items:
                        if key not in nb.cite_order:
                            nb.cite_order.append(key)
    return nb


class _AppStub:
    def __init__(self, app):
        from .model import Src
        self.src = Src(app.file or "diploma.yaml", 1)
        self.app = app


def _number_obj(b, prefix, cnt, reg, issues, part):
    kinds = {Figure: "fig", Table: "tbl", Listing: "lst", Formula: "eq"}
    kind = kinds.get(type(b))
    if not kind:
        return
    if prefix is None:
        if kind != "eq":
            issues.err("STR", "рисунки, таблицы и листинги во введении/заключении не допускаются", b.src)
        prefix = "0"
    cnt[kind] = cnt.get(kind, 0) + 1
    b.number = f"{prefix}.{cnt[kind]}"
    reg(kind, b.label, f"({b.number})" if kind == "eq" else b.number, b)


def cite_numbers(pr, nb: Numbering, order: str):
    keys = list(pr.sources.keys())
    if order == "citation":
        ordered = [k for k in nb.cite_order if k in pr.sources] + [k for k in keys if k not in nb.cite_order]
    else:
        from .bib import sort_key
        ordered = sorted(keys, key=lambda k: sort_key(pr.sources[k]))
    nb.cite_num = {k: i + 1 for i, k in enumerate(ordered)}
    return ordered


def format_cite(c: Cite, nb: Numbering) -> str:
    nums = []
    parts = []
    for key, loc in c.items:
        n = nb.cite_num.get(key)
        if n is None:
            parts.append("?")
            continue
        if loc:
            parts.append(f"{n}, {loc}")
        else:
            nums.append(n)
    # сжимаем 3, 4, 5 -> 3–5
    nums.sort()
    out = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(f"{nums[i]}–{nums[j]}" if j - i >= 2 else ", ".join(str(x) for x in nums[i:j + 1]))
        i = j + 1
    items = out + parts
    return "[" + "; ".join(items) + "]" if parts and out else "[" + ", ".join(items) + "]"
