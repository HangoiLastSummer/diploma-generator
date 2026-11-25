"""Валидатор входа: всё, что видно по тексту и структуре до вёрстки."""
from __future__ import annotations

import math
import re

from .model import (Bold, Cite, Code, Emph, Figure, Formula, Heading, ListBlock, Listing, Math, Paragraph,
                    Ref, Table, Text, Url, Where, block_items, plain, walk_inlines)
from .numbering import Numbering

LISTING_CHARS = 65            # символов Courier New 12 pt в рамке шириной 170 мм
LISTING_MAX_LINES = 26        # ≈ половина страницы
REF_WORDS = {
    "fig": ("рисун",), "tbl": ("таблиц",), "lst": ("листинг",),
    "eq": ("формул", "выражени", "уравнени", "соотношени"), "app": ("приложени",),
}
KIND_NAME = {"fig": "рисунок", "tbl": "таблицу", "lst": "листинг", "eq": "формулу", "app": "приложение"}
TEXTUAL = (Paragraph, ListBlock)


def listing_visual_lines(code: str) -> int:
    return sum(max(1, math.ceil(len(ln) / LISTING_CHARS)) for ln in code.split("\n"))


def validate(pr, nb: Numbering, issues):
    parts_main = [p for p in (pr.intro, pr.body, pr.conclusion) if p]
    allparts = parts_main + pr.appendices
    for app in pr.appendices:
        for b in app.blocks:
            if isinstance(b, Listing):
                b._appendix_free = True
            if isinstance(b, Figure) and app.kind == "user-guide":
                b._appendix_free = True      # E11: в руководстве допустима подпись только с номером

    _structure(pr, issues)
    _refs(pr, nb, allparts, issues)
    _cites(pr, allparts, issues)
    _abbrevs(pr, parts_main, issues)
    _text_rules(parts_main, issues)
    _objects(pr, allparts, issues)
    _annotation(pr, issues)


# ---------------------------------------------------------------- структура

def _structure(pr, issues):
    body = pr.body.blocks if pr.body else []
    if body and not (isinstance(body[0], Heading) and body[0].level == 1):
        issues.err("STR", "основная часть должна начинаться с заголовка главы (# …)", body[0].src)

    for part in [p for p in (pr.intro, pr.body, pr.conclusion) if p] + pr.appendices:
        bl = part.blocks
        check_end = part.role != "appendix" or part.kind == "user-guide"
        for i, b in enumerate(bl):
            if isinstance(b, Heading) and b.level <= 3:
                nxt = bl[i + 1] if i + 1 < len(bl) else None
                if nxt is None:
                    issues.err("TODO", "после заголовка нет текста", b.src)
                elif isinstance(nxt, Heading) and nxt.level <= b.level and b.level < 4:
                    issues.err("TODO", f"раздел «{plain(b.inlines)[:40]}» пуст", b.src, "напиши текст раздела")
                elif isinstance(nxt, (Figure, Table, Listing, Formula, Where)):
                    issues.err("E6", "раздел не может начинаться с рисунка, таблицы, листинга или формулы", nxt.src,
                               "поставь перед ним абзац, который вводит объект и ссылается на него")
                # конец предыдущего раздела
                if i > 0 and check_end:
                    _check_section_end(bl[i - 1], issues)
        if bl and check_end and part.role != "appendix":
            _check_section_end(bl[-1], issues)
        elif bl and part.kind == "user-guide":
            _check_section_end(bl[-1], issues)

    # «Выводы» в конце каждой главы
    chapters = []
    for b in body:
        if isinstance(b, Heading) and b.level == 1:
            chapters.append([b])
        elif isinstance(b, Heading) and b.level == 2 and chapters:
            chapters[-1].append(b)
    for ch in chapters:
        subs = ch[1:]
        if subs and plain(subs[-1].inlines).strip().lower() != "выводы":
            issues.warn("B8", f"глава {ch[0].number} не заканчивается подразделом «Выводы»", ch[0].src,
                        "добавь последним подразделом ## Выводы")

    # приложение-руководство: обязательные разделы
    for app in pr.appendices:
        if app.kind != "user-guide":
            continue
        titles = " | ".join(plain(b.inlines).lower() for b in app.blocks if isinstance(b, Heading))
        for need, hint in (("введение", "# Введение"), ("установ", "руководство по установке"),
                           ("назначение", "назначение программы"), ("системные требования", "системные требования"),
                           ("заключение", "# Заключение")):
            if need not in titles:
                issues.warn("J7", f"в руководстве пользователя нет раздела «{hint}»",
                            app.blocks[0].src if app.blocks else None)


def _check_section_end(b, issues):
    if isinstance(b, Heading):
        return
    if not isinstance(b, TEXTUAL):
        issues.err("E8", "пункт должен заканчиваться текстом, а не рисунком, таблицей, листингом или формулой", b.src,
                   "добавь после объекта абзац с пояснением или выводом")


# ---------------------------------------------------------------- ссылки

def _block_seq(allparts):
    seq = []
    for p in allparts:
        for b in p.blocks:
            seq.append(b)
    return seq


def _refs(pr, nb, allparts, issues):
    seq = _block_seq(allparts)
    pos = {id(b): i for i, b in enumerate(seq)}
    first_ref = {}
    for i, b in enumerate(seq):
        for owner, inl in block_items([b]):
            prev_text = ""
            for x in inl:
                if isinstance(x, Text):
                    prev_text = x.s
                elif isinstance(x, (Emph, Bold)):
                    prev_text = plain(x.children)
                elif isinstance(x, Ref):
                    key = (x.kind, x.label)
                    if key not in nb.labels:
                        issues.err("REF", f"нет объекта с меткой @{x.kind}:{x.label}", getattr(owner, "src", b.src))
                    else:
                        first_ref.setdefault(key, i)
                        words = re.findall(r"[А-Яа-яЁё]+", prev_text.lower())
                        last = words[-1] if words else ""
                        if not any(last.startswith(w) for w in REF_WORDS[x.kind]):
                            issues.warn("REF", f"перед @{x.kind}:{x.label} ожидается слово «{KIND_NAME[x.kind]}» в нужном падеже",
                                        getattr(owner, "src", b.src),
                                        f"например: «{'на рисунке' if x.kind == 'fig' else 'в таблице' if x.kind == 'tbl' else 'в листинге' if x.kind == 'lst' else 'по формуле' if x.kind == 'eq' else 'в приложении'} @{x.kind}:{x.label}»")
                    prev_text = ""
                else:
                    prev_text = ""

    for key, obj in nb.objects.items():
        kind, label = key
        if kind == "app":
            continue
        if key not in first_ref:
            if kind == "eq":
                continue
            issues.err("E4", f"на {KIND_NAME[kind]} @{kind}:{label} нет ссылки в тексте", obj.src,
                       f"добавь в абзац перед ним «… {('на рисунке' if kind == 'fig' else 'в таблице' if kind == 'tbl' else 'в листинге')} @{kind}:{label}»")
        elif first_ref[key] > pos.get(id(obj), 10 ** 9):
            issues.warn("E4", f"первая ссылка на @{kind}:{label} стоит после самого объекта", obj.src,
                        "ссылка должна предшествовать объекту")

    # объекты без меток
    for b in seq:
        if isinstance(b, (Figure, Table, Listing)) and not b.label and not (isinstance(b, Listing) and getattr(b, "_appendix_free", False)):
            k = "fig" if isinstance(b, Figure) else "tbl" if isinstance(b, Table) else "lst"
            issues.err("E4", f"у объекта нет метки — на него невозможно сослаться", b.src,
                       f"добавь {{#{k}:имя}} и ссылку @{k}:имя в тексте перед ним")
        if isinstance(b, (Figure, Table, Listing)) and not b.caption and not getattr(b, "_appendix_free", False):
            issues.err("E2", "у объекта нет названия", b.src,
                       "рисунок: ![Название](файл); таблица: строка «Таблица: Название» над ней; листинг: caption=\"…\"")


def _cites(pr, allparts, issues):
    used = {}
    for p in allparts:
        for owner, inl in block_items(p.blocks):
            for x in walk_inlines(inl):
                if isinstance(x, Cite):
                    for key, _ in x.items:
                        used.setdefault(key, owner.src)
                        if key not in pr.sources:
                            issues.err("I3", f"нет источника «{key}» в sources.yaml", owner.src)
    for key, s in pr.sources.items():
        if key not in used:
            issues.err("I3", f"источник «{key}» нигде не процитирован", s["_src"],
                       "сошлись на него [@" + key + "] или удали из списка")
    unchecked = [k for k, s in pr.sources.items() if s.get("checked") is not True]
    if unchecked:
        issues.warn("SRC", f"непроверенные источники ({len(unchecked)}): {', '.join(unchecked)}",
                    pr.sources[unchecked[0]]["_src"], "убедись, что источник существует, и поставь checked: true")
    pr._used_cites = set(used)


# ---------------------------------------------------------------- аббревиатуры

ABBR_CYR = re.compile(r"(?<![А-Яа-яЁёA-Za-z])[А-ЯЁ]{2,}(?![А-Яа-яЁё])")
ABBR_LAT = re.compile(r"(?<![A-Za-z0-9.])[A-Z][A-Z0-9]{1,}(?![A-Za-z0-9]|\.[A-Za-z])")
ROMAN = re.compile(r"^[IVXLCDM]+$")


def _abbrevs(pr, parts, issues):
    declared = {str(k): str(v) for k, v in (pr.cfg.get("abbreviations") or {}).items()}
    latin_undeclared = []
    white = set(pr.cfg.get("abbrev_whitelist") or [])
    seen = {}
    for p in parts:
        for owner, inl in block_items(p.blocks):
            if isinstance(owner, (Listing, Heading)):
                continue
            buf = ""
            for x in walk_inlines(inl):
                if isinstance(x, Text):
                    buf += x.s
                elif isinstance(x, (Code, Math, Url, Ref, Cite)):
                    buf += " ¤ "
            for rx, cyr in ((ABBR_CYR, True), (ABBR_LAT, False)):
                for m in rx.finditer(buf):
                    tok = m.group(0)
                    if tok in white or ROMAN.match(tok) or tok in seen:
                        if tok not in seen:
                            seen[tok] = None
                        continue
                    seen[tok] = owner.src
                    ctx_before = buf[max(0, m.start() - 2):m.start()]
                    ctx_after = buf[m.end():m.end() + 3]
                    expanded = ctx_before.endswith("(") or ctx_after.lstrip().startswith("(") or ctx_after.startswith(" –")
                    if tok not in declared:
                        if isinstance(owner, Heading):
                            pass
                        if cyr:
                            issues.err("C6", f"аббревиатура «{tok}» не объявлена в abbreviations (diploma.yaml)", owner.src,
                                       f"добавь «{tok}: полная форма» и раскрой её при первом упоминании")
                        else:
                            latin_undeclared.append((tok, owner.src))
                    elif not expanded:
                        issues.warn("C6", f"первое упоминание «{tok}» без расшифровки", owner.src,
                                    f"напиши «{declared[tok]} ({tok})»")
    if latin_undeclared:
        toks = ", ".join(t for t, _ in latin_undeclared)
        issues.warn("C6", f"латинские аббревиатуры без объявления ({len(latin_undeclared)}): {toks}", latin_undeclared[0][1],
                    "аббревиатуры (API, LLM…) объяви в abbreviations и раскрой при первом упоминании; имена продуктов игнорируй")
    for k in declared:
        if k not in seen:
            issues.warn("C6", f"аббревиатура «{k}» объявлена, но в тексте не встречается",
                        None, "убери её из abbreviations")


# ---------------------------------------------------------------- текст

MANUAL_REF = re.compile(r"\b((?i:рисун\w*|таблиц\w*|листинг\w*|приложени\w*))\s+((?:\d+\.\d+)|(?:[А-Я]\.\d+)|(?:[А-Я])(?![А-Яа-яЁёA-Za-z]))")
MANUAL_CITE = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*(?:,\s*с\.\s*[\d–-]+)?\]")
NUM_WORD = re.compile(r"(?<![\d.,\w])([1-9])\s+([а-яё]{3,})")
UNITISH = re.compile(r"^(руб|тыс|млн|млрд|лет|год|час|мин|сек|мес|дн|недел|ядр|поток|бит|байт|раз|шт|стр|пикс|процент|градус|километ|метр|сантим|миллим|килограм|грамм|секунд|минут|сут)")


def _text_rules(parts, issues):
    for p in parts:
        for owner, inl in block_items(p.blocks):
            if isinstance(owner, Listing):
                continue
            for x in walk_inlines(inl):
                if isinstance(x, Bold) and not isinstance(owner, Heading):
                    issues.warn("C11", "жирный шрифт в тексте", owner.src,
                                "для терминов используй *курсив*, для подзаголовка — #### Заголовок")
                if isinstance(x, Text):
                    m = MANUAL_REF.search(x.s)
                    if m:
                        issues.err("REF", f"номер объекта написан руками: «{m.group(0)}»", owner.src,
                                   "используй метку: «на рисунке @fig:имя»")
                    m = MANUAL_CITE.search(x.s)
                    if m:
                        issues.err("I1", f"ссылка на источник написана руками: «{m.group(0)}»", owner.src,
                                   "используй [@ключ] из sources.yaml")
                    for m in NUM_WORD.finditer(x.s):
                        if not UNITISH.match(m.group(2)):
                            issues.warn("C7", f"число без единиц измерения цифрой: «{m.group(0)}»", owner.src,
                                        "числа от одного до девяти без единиц пишутся словами")
        for b in p.blocks:
            if isinstance(b, Paragraph):
                t = plain(b.inlines)
                sentences = len(re.findall(r"[.!?…](?:\s+|$)(?=[А-ЯЁA-Z«\d]|$)", t))
                if sentences > 8:
                    issues.warn("C4", f"абзац из {sentences} предложений", b.src, "раздели на 2–3 абзаца по 4–5 предложений")


# ---------------------------------------------------------------- объекты

def _objects(pr, allparts, issues):
    from PIL import Image, ImageStat
    for p in allparts:
        in_main = p.role != "appendix"
        for b in p.blocks:
            if isinstance(b, Listing):
                if in_main:
                    vl = listing_visual_lines(b.code)
                    if vl > LISTING_MAX_LINES:
                        issues.err("G4", f"листинг занимает ~{vl} строк, это больше половины страницы ({LISTING_MAX_LINES})",
                                   b.src, "сократи до сути или вынеси в приложение и сошлись на него")
                    long = [ln for ln in b.code.split("\n") if len(ln) > LISTING_CHARS]
                    if long:
                        issues.warn("G6", f"{len(long)} строк листинга длиннее {LISTING_CHARS} символов — будут перенесены",
                                    b.src, "разбей длинные строки вручную")
            elif isinstance(b, Figure):
                path = pr.path(b.path) if not str(b.path).startswith("/") else b.path
                try:
                    im = Image.open(path)
                except Exception:
                    issues.err("E1", f"не найден или не читается файл рисунка {b.path}", b.src)
                    continue
                w, h = im.size
                frac = b.width or 1.0
                target_mm = 170 * frac
                nat_mm = w * 25.4 / 96
                if nat_mm > target_mm * 2.2:
                    issues.warn("E9", f"рисунок будет уменьшен в {nat_mm / target_mm:.1f} раза — мелкий текст на нём станет нечитаемым",
                                b.src, "обрежь скриншот до нужной области или увеличь шрифт в исходной схеме")
                try:
                    g = im.convert("L")
                    g.thumbnail((200, 200))
                    lum = ImageStat.Stat(g).mean[0] / 255
                    if lum < 0.35:
                        issues.warn("E10", "тёмный рисунок (вероятно, скриншот в тёмной теме)", b.src,
                                    "для печати лучше светлая тема или инверсия цветов")
                except Exception:
                    pass
                b._size_px = (w, h)
            elif isinstance(b, Table):
                empty = 0
                for row in b.rows:
                    for ci, cell in enumerate(row):
                        t = plain(cell).strip()
                        if t in ("<", "^"):
                            continue
                        if t in ("-", "—", "--"):
                            row[ci] = [Text("–")]
                            empty += 1
                            continue
                        if t in ('"', "〃", "»", "″", "-//-", "—//—"):
                            issues.err("F6", "повтор значения кавычками в таблице не допускается", b.src,
                                       "повтори значение полностью")
                        if not t:
                            row[ci] = [Text("–")]
                            empty += 1
                if empty:
                    issues.fixed("F5", f"пустые ячейки ({empty}) заменены прочерком", b.src)


def _annotation(pr, issues):
    from .model import Src
    ann = pr.cfg.get("annotation") or {}
    for lang in ("ru", "en"):
        t = ann.get(lang) or ""
        words = len(re.findall(r"\w+", t))
        if words > 75:
            issues.warn("J4", f"аннотация ({lang}) — {words} слов, по методичке около 60",
                        Src(pr.cfg.get("_config_file", "diploma.yaml"), pr.cfg_lines.line("annotation", lang)),
                        "сократи до 55–70 слов")
    if pr.intro:
        t = " ".join(plain(inl).lower() for _, inl in block_items(pr.intro.blocks))
        for stem, what in (("актуальн", "актуальность"), ("цел", "цель работы")):
            if stem not in t:
                issues.warn("J5", f"во введении не найдено: {what}", pr.intro.blocks[0].src if pr.intro.blocks else None)
