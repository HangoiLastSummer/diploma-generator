"""Командная строка: vkr init | check | fix | stats | build | preview | hook | rules | doctor."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .issues import ERROR, FIXED, WARNING

DOCS = Path(__file__).parent / "docs"


def find_config(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    p = Path.cwd()
    for d in [p] + list(p.parents):
        if (d / "diploma.yaml").exists():
            return d / "diploma.yaml"
    sys.exit("не найден diploma.yaml (запусти в папке проекта или укажи -c путь)")


def fmt_issue(i, root: Path | None = None) -> str:
    loc = i.loc()
    s = f"{loc + ' ' if loc else ''}[{i.rule}] {i.message}"
    if i.hint:
        s += f" → {i.hint}"
    return s


def write_report(issues, path_md: Path, path_json: Path, stats=None):
    groups = [("Ошибки", ERROR), ("Предупреждения", WARNING), ("Исправлено автоматически", FIXED)]
    lines = ["# Отчёт сборки ВКР", ""]
    if stats:
        lines += [f"Страниц всего: {stats.get('pages_total')}, без приложений: {stats.get('pages_no_app')} "
                  f"(введение {stats.get('intro')}, основная часть {stats.get('main')}, заключение {stats.get('conclusion')})", ""]
    for title, sev in groups:
        items = [i for i in issues if i.severity == sev]
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        for i in items:
            loc = f"`{i.loc()}` " if i.loc() else ""
            lines.append(f"- {loc}**{i.rule}** {i.message}" + (f" — {i.hint}" if i.hint else ""))
        lines.append("")
    path_md.write_text("\n".join(lines), encoding="utf-8")
    path_json.write_text(json.dumps({"stats": stats or {}, "issues": [i.to_dict() for i in issues]},
                                    ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ команды

def cmd_check(a):
    from .pipeline import prepare
    cfg = find_config(a.config)
    pr, nb, issues = prepare(cfg, only_file=a.file)
    shown = [i for i in issues if i.severity != FIXED or a.verbose]
    if a.format == "json":
        print(json.dumps([i.to_dict() for i in shown], ensure_ascii=False, indent=1))
    else:
        for sev, title in ((ERROR, "Ошибки"), (WARNING, "Предупреждения"), (FIXED, "Исправлено при сборке")):
            items = [i for i in shown if i.severity == sev]
            if items:
                print(f"\n{title} ({len(items)}):")
                for i in items:
                    print("  " + fmt_issue(i))
        if not issues.errors:
            print("\nОшибок нет." + (" Можно собирать: vkr build" if not a.file else ""))
    return 1 if issues.errors else 0


def cmd_fix(a):
    from .fixsrc import fix_markdown
    from .project import load_project
    cfg = find_config(a.config)
    pr = load_project(cfg, parse_md=True)
    total = 0
    for rel in pr.md_texts:
        p = pr.path(rel)
        text = p.read_text(encoding="utf-8")
        new, n = fix_markdown(text)
        if n and new != text:
            p.write_text(new, encoding="utf-8")
            print(f"  {rel}: {n} правок")
            total += n
    print(f"Исправлено строк: {total}" if total else "Исправлять нечего.")
    return 0


def cmd_stats(a):
    from .model import Heading, Listing, block_items, plain
    from .project import load_project
    cfg = find_config(a.config)
    pr = load_project(cfg)
    rows = []
    words_per_page = 270

    def count(blocks):
        n = 0
        for owner, inl in block_items(blocks):
            if isinstance(owner, (Listing,)):
                continue
            n += len(re.findall(r"\w+", plain(inl)))
        return n

    def targets(rel):
        text = pr.md_texts.get(rel, "")
        out = []
        for m in re.finditer(r"^##\s+(.+?)\s*$\s*<!--(.*?)-->", text, flags=re.M | re.S):
            mm = re.search(r"ОБЪЁМ:\s*([\d,]+)\s*[–-]\s*([\d,]+)", m.group(2))
            if mm:
                out.append((m.group(1).strip(), float(mm.group(1).replace(",", ".")), float(mm.group(2).replace(",", "."))))
        return out

    def section_rows(part, rel):
        tg = {t: (lo, hi) for t, lo, hi in targets(rel)}
        cur, buf = None, []
        res = []
        for b in part.blocks + [None]:
            if b is None or (isinstance(b, Heading) and b.level <= 2):
                if cur is not None:
                    w = count(buf)
                    res.append((cur, w, tg.get(cur)))
                if b is not None:
                    cur = plain(b.inlines)
                    buf = []
                continue
            buf.append(b)
        return res

    total = 0
    if pr.intro:
        w = count(pr.intro.blocks)
        total += w
        rows.append(("ВВЕДЕНИЕ", w, (1, 2)))
    for rel in (pr.cfg.get("content") or {}).get("chapters") or []:
        from .parser import parse_markdown
        from .issues import Issues
        from .model import Part
        part = Part("body", parse_markdown(pr.md_texts.get(str(Path(rel)), ""), rel, Issues()))
        for title, w, tg in section_rows(part, str(Path(rel))):
            total += w
            rows.append(("  " + title, w, tg))
    if pr.conclusion:
        w = count(pr.conclusion.blocks)
        total += w
        rows.append(("ЗАКЛЮЧЕНИЕ", w, (1, 2)))
    print(f"{'Раздел':<70} {'слов':>6} {'≈стр':>5}  цель")
    for title, w, tg in rows:
        pages = w / words_per_page
        mark = ""
        if tg:
            lo, hi = tg
            mark = f"{lo:g}–{hi:g}" + ("  мало" if pages < lo * 0.9 else "  много" if pages > hi * 1.1 else "  ок")
        print(f"{title[:70]:<70} {w:>6} {pages:>5.1f}  {mark}")
    print(f"{'ИТОГО (текст без рисунков, таблиц, листингов)':<70} {total:>6} {total / words_per_page:>5.1f}  50–70 вместе с рисунками")
    return 0


def cmd_build(a):
    from .pipeline import build
    cfg = find_config(a.config)
    out = Path(a.output) if a.output else cfg.parent / "vkr.docx"
    print(f"Сборка {out.name} …")
    pr, issues, res = build(cfg, out, layout=not a.no_layout, pdf=True, force=a.force,
                            log=(lambda *x: None) if a.quiet else print)
    stats = (res or {}).get("stats")
    write_report(issues, cfg.parent / "report.md", cfg.parent / "report.json", stats)
    errs, warns = issues.errors, issues.warnings
    if errs and not res and not (a.force and out.exists()):
        print(f"\nСборка остановлена: ошибок {len(errs)}. Подробно — report.md или vkr check")
        for i in errs[:15]:
            print("  " + fmt_issue(i))
        return 1
    print(f"\nГотово: {out}" + (f" и {out.with_suffix('.pdf').name}" if res and res.get("pdf") else ""))
    if stats:
        print(f"Страниц: {stats['pages_total']} (без приложений {stats['pages_no_app']})")
    print(f"Ошибок: {len(errs)}, предупреждений: {len(warns)} — см. report.md")
    return 1 if errs else 0


def cmd_preview(a):
    cfg = find_config(a.config)
    pdf = Path(a.pdf) if a.pdf else cfg.parent / "vkr.pdf"
    if not pdf.exists():
        sys.exit(f"нет {pdf.name}: сначала vkr build")
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", a.pages)
    if not m:
        sys.exit("--pages 12 или 12-14")
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    outdir = cfg.parent / ".vkr" / "preview"
    outdir.mkdir(parents=True, exist_ok=True)
    import pymupdf
    doc = pymupdf.open(str(pdf))
    for p in range(first, min(last, len(doc)) + 1):
        pix = doc[p - 1].get_pixmap(dpi=a.dpi)
        f = outdir / f"page-{p:03d}.png"
        pix.save(str(f))
        print(f)
    return 0


def cmd_hook(a):
    """PostToolUse-хук Claude Code: проверка изменённого файла, ошибки — в stderr с кодом 2."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    fp = (data.get("tool_input") or {}).get("file_path") or ""
    if not fp or not (fp.endswith(".md") or fp.endswith(".yaml") or fp.endswith(".yml")):
        return 0
    cwd = Path(data.get("cwd") or os.getcwd())
    cfgp = None
    for d in [Path(fp).resolve().parent] + list(Path(fp).resolve().parents) + [cwd]:
        if (d / "diploma.yaml").exists():
            cfgp = d / "diploma.yaml"
            break
    if not cfgp:
        return 0
    try:
        rel = str(Path(fp).resolve().relative_to(cfgp.parent))
    except ValueError:
        return 0
    if rel in ("CLAUDE.md", "README.md", "FORMAT.md", "RULES.md") or rel.startswith("context/") or rel.startswith(".claude/"):
        return 0
    from .pipeline import prepare
    only = None if rel.endswith((".yaml", ".yml")) else rel
    pr, nb, issues = prepare(cfgp, only_file=only)
    # незаполненные разделы — это «ещё не написано», а не ошибка правки: хук о них молчит
    errs = [i for i in issues.errors if i.rule != "TODO"]
    if not errs:
        return 0
    lines = [f"vkr check: {len(errs)} ошибок в {rel} — исправь:"]
    for i in errs[:20]:
        lines.append("  " + fmt_issue(i))
    if len(errs) > 20:
        lines.append(f"  … и ещё {len(errs) - 20}")
    w = [i for i in issues.warnings if i.file == rel]
    if w:
        lines.append(f"(+ {len(w)} предупреждений: vkr check --file {rel})")
    print("\n".join(lines), file=sys.stderr)
    return 2


def cmd_rules(a):
    text = (DOCS / "RULES.md").read_text(encoding="utf-8")
    if not a.id:
        print(text)
        return 0
    pat = re.compile(rf"^- \*\*{re.escape(a.id.upper())}\*\*.*?(?=^- \*\*|^## |\Z)", re.M | re.S)
    m = pat.search(text)
    print(m.group(0).strip() if m else f"правило {a.id} не найдено")
    return 0 if m else 1


def cmd_init(a):
    from . import templates as T
    dest = Path(a.dir).resolve()
    if (dest / "diploma.yaml").exists() and not a.force:
        sys.exit(f"{dest}/diploma.yaml уже есть (—force, чтобы перезаписать шаблон)")
    if a.type not in T.TYPES:
        sys.exit("тип работы: " + ", ".join(T.TYPES))
    tname, ch1, ch2, ch3 = T.TYPES[a.type]
    for d in ("chapters", "appendix", "img", "context", ".claude/commands"):
        (dest / d).mkdir(parents=True, exist_ok=True)
    year = a.year or (dt.date.today().year + (1 if dt.date.today().month >= 9 else 0))
    files = {
        "diploma.yaml": T.DIPLOMA_YAML.format(year=year),
        "sources.yaml": T.SOURCES_YAML,
        "chapters/intro.md": T.INTRO_MD,
        "chapters/1-analysis.md": T.chapter_md(1, ch1[0], ch1[1], tname),
        "chapters/2-design.md": T.chapter_md(2, ch2[0], ch2[1], tname),
        "chapters/3-impl.md": T.chapter_md(3, ch3[0], ch3[1], tname),
        "chapters/conclusion.md": T.CONCL_MD,
        "appendix/user-guide.md": T.UG_MD,
        "context/project.md": T.PROJECT_MD,
        "context/notes.md": T.NOTES_MD,
        ".gitignore": "vkr.docx\nvkr.pdf\nreport.md\nreport.json\n.vkr/\n~$*.docx\n",
    }
    for rel, content in files.items():
        p = dest / rel
        if p.exists() and not a.force:
            continue
        p.write_text(content, encoding="utf-8")
    for name in ("CLAUDE.md", "FORMAT.md", "RULES.md"):
        shutil.copy(DOCS / name, dest / name)
    shutil.copytree(DOCS / "claude", dest / ".claude", dirs_exist_ok=True)
    (dest / "img" / ".gitkeep").touch()
    print(f"Проект создан: {dest} (тип: {tname})")
    print("Дальше: заполни diploma.yaml и context/project.md, затем в этой папке запусти claude и /section 1.1")
    return 0


def cmd_doctor(a):
    ok = True

    def line(good, what, fix=""):
        nonlocal ok
        ok &= good
        print(("  ✓ " if good else "  ✗ ") + what + ("" if good or not fix else f"  →  {fix}"))
    so = shutil.which("soffice") or shutil.which("libreoffice")
    line(bool(so), "LibreOffice (нужен для вёрстки)", "sudo apt install libreoffice-writer")
    math_ok = any(Path(p).exists() for p in ("/usr/lib/libreoffice/program/libsmlo.so",
                                             "/usr/lib/libreoffice/program/libsmdlo.so",
                                             "/Applications/LibreOffice.app/Contents/Frameworks/libsmlo.dylib"))
    line(math_ok, "LibreOffice Math (иначе формулы пропадут в PDF)", "sudo apt install libreoffice-math")
    hyph = any(Path(p).exists() for p in ("/usr/share/hyphen/hyph_ru_RU.dic",))
    line(hyph, "русские переносы для LibreOffice", "sudo apt install hyphen-ru")
    fc = subprocess.run(["fc-list"], capture_output=True, text=True).stdout if shutil.which("fc-list") else ""
    line("Times New Roman" in fc or "Liberation Serif" in fc, "шрифт Times New Roman или Liberation Serif",
         "sudo apt install fonts-liberation2 (или ttf-mscorefonts-installer)")
    line("Courier New" in fc or "Liberation Mono" in fc, "шрифт Courier New или Liberation Mono", "sudo apt install fonts-liberation2")
    line(bool(shutil.which("pandoc")), "pandoc (формулы LaTeX → Word)", "sudo apt install pandoc")
    for mod, pkg in (("docx", "python-docx"), ("pymupdf", "pymupdf"), ("yaml", "pyyaml"), ("PIL", "pillow"),
                     ("pytrovich", "pytrovich")):
        try:
            __import__(mod)
            line(True, f"python: {pkg}")
        except ImportError:
            line(False, f"python: {pkg}", f"pip install {pkg}")
    print("Всё готово." if ok else "Исправь пункты с ✗.")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vkr", description="Генератор ВКР по требованиям кафедры ПОВТ ПГУ")
    ap.add_argument("-c", "--config", help="путь к diploma.yaml (по умолчанию ищется в текущей папке и выше)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="создать проект из шаблона")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--type", default="client-server", help="client-server | is | web | compute | graphics | research | project")
    s.add_argument("--year", type=int)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("check", help="валидатор без вёрстки")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.add_argument("--file", help="показать только проблемы этого файла")
    s.add_argument("-v", "--verbose", action="store_true", help="показывать и автоисправления")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("fix", help="безопасные правки в исходниках .md")
    s.set_defaults(fn=cmd_fix)

    s = sub.add_parser("stats", help="объём по разделам")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("build", help="собрать vkr.docx и vkr.pdf")
    s.add_argument("-o", "--output")
    s.add_argument("--no-layout", action="store_true", help="без цикла вёрстки (быстро, без номеров страниц)")
    s.add_argument("--force", action="store_true", help="собрать, даже если есть ошибки")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("preview", help="PNG страниц из vkr.pdf")
    s.add_argument("--pages", required=True)
    s.add_argument("--pdf")
    s.add_argument("--dpi", type=int, default=80)
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("hook", help="хук Claude Code")
    s.add_argument("event", choices=["post-edit"])
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("rules", help="показать правило из RULES.md")
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_rules)

    s = sub.add_parser("doctor", help="проверить окружение")
    s.set_defaults(fn=cmd_doctor)

    a = ap.parse_args(argv)
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
