"""Конвейер: загрузка → нумерация → типографика → валидация → сборка → вёрстка."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .issues import Issues
from .math_omml import MathCache
from .model import Formula, Math, block_items, walk_inlines
from .numbering import cite_numbers, number_project
from .project import load_project
from .typo import apply_block
from .validate import validate


def prepare(config_path, only_file: str | None = None):
    pr = load_project(config_path)
    issues = pr.issues
    if issues.errors and not (pr.body or pr.intro):
        return pr, None, issues
    nb = number_project(pr, issues)
    per_file = Counter()
    first_src = {}
    for part in [p for p in (pr.intro, pr.body, pr.conclusion) if p] + pr.appendices:
        for b in part.blocks:
            n = apply_block(b)
            if n:
                per_file[b.src.file] += n
                first_src.setdefault(b.src.file, b.src)
    for f, n in per_file.items():
        issues.fixed("C8", f"типографика: {n} правок (тире, кавычки, пробелы, пунктуация перечислений)", first_src[f])
    validate(pr, nb, issues)
    order = (pr.cfg.get("bibliography") or {}).get("order", "alphabetical")
    pr.bib_order = cite_numbers(pr, nb, order)
    if only_file:
        keep = Issues(i for i in issues if not i.file or Path(i.file) == Path(only_file)
                      or Path(i.file).name == Path(only_file).name)
        return pr, nb, keep
    return pr, nb, issues


def collect_math(pr):
    texs = []
    for part in [p for p in (pr.intro, pr.body, pr.conclusion) if p] + pr.appendices:
        for b in part.blocks:
            if isinstance(b, Formula):
                texs.append(b.tex)
        for _, inl in block_items(part.blocks):
            for x in walk_inlines(inl):
                if isinstance(x, Math):
                    texs.append(x.tex)
    return texs


def build(config_path, out_path, layout=True, pdf=True, log=print, force=False):
    pr, nb, issues = prepare(config_path)
    if issues.errors and not force:
        return pr, issues, None
    if nb is None:
        return pr, issues, None
    mc = MathCache()
    mc.prepare(collect_math(pr))
    for tex, err in mc.errors.items():
        issues.err("H1", f"формула не разобрана: {tex[:60]} ({err})")
    from .builder import Builder
    if not layout:
        b = Builder(pr, nb, issues, mc)
        b.bib_order = pr.bib_order
        b.build(out_path)
        return pr, issues, None
    from .layout import layout_loop
    result = layout_loop(pr, nb, issues, mc, Path(out_path), want_pdf=pdf, log=log)
    return pr, issues, result
