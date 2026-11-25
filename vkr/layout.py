"""Цикл вёрстки: рендер через LibreOffice → анализ PDF → подсказки билдеру → повторная сборка.

Что решается здесь (класс LAYOUT в RULES.md):
- номера страниц в оглавлении;
- разрыв таблиц: «Продолжение таблицы N» + повтор шапки (F4);
- подраздел у низа страницы с 1–2 строками текста → перенос на новую страницу (B7);
- последняя строка абзаца из одного слова → уплотнение до 0,3 pt (C3);
- предупреждения: рисунок в начале страницы (E7), большое пустое место (C10), объём (J3).
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pymupdf

PT_PER_MM = 72 / 25.4
TOP = 20 * PT_PER_MM                 # 56.7
BOTTOM = (297 - 20) * PT_PER_MM      # 785.2
LEFT = 30 * PT_PER_MM                # 85.0
RIGHT = (210 - 10) * PT_PER_MM       # 566.9
INDENT = 12.5 * PT_PER_MM            # 35.4


# ------------------------------------------------------------------ рендер

def soffice_bin():
    for b in ("soffice", "libreoffice"):
        p = shutil.which(b)
        if p:
            return p
    raise RuntimeError("не найден LibreOffice (soffice). Установи: sudo apt install libreoffice-writer libreoffice-math hyphen-ru")


def render_pdf(docx: Path, outdir: Path) -> Path:
    prof = Path(tempfile.gettempdir()) / "vkr_lo_profile"
    cmd = [soffice_bin(), f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
           "--outdir", str(outdir), str(docx)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    pdf = outdir / (docx.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"LibreOffice не создал PDF: {r.stderr.strip()[:300]}")
    return pdf


# ------------------------------------------------------------------ анализ PDF

def _norm(s: str) -> str:
    return re.sub(r"[\s ­\-–]+", "", s).lower()


def _hlines(page, x0=LEFT - 5, x1=RIGHT + 5):
    ys = []
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.y - p2.y) < 0.6 and abs(p1.x - p2.x) > 10 and min(p1.x, p2.x) >= x0 - 1 and max(p1.x, p2.x) <= x1 + 1:
                    ys.append((p1.y + p2.y) / 2)
            elif it[0] == "re":
                r = it[1]
                if r.height < 1.6 and r.width > 10 and r.x0 >= x0 - 1 and r.x1 <= x1 + 1:
                    ys.append((r.y0 + r.y1) / 2)
    ys.sort()
    out = []
    for y in ys:
        if not out or y - out[-1] > 1.5:
            out.append(y)
    return out


def _lines(page):
    """Строки текста: [(x0, y0, x1, y1, text, bold)] без колонтитула."""
    out = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            if y0 > BOTTOM - 2:          # колонтитул
                continue
            text = "".join(s["text"] for s in ln["spans"])
            bold = all("Bold" in s["font"] or (s["flags"] & 16) for s in spans)
            out.append((x0, y0, x1, y1, text, bold))
    # объединяем фрагменты одной строки (LibreOffice иногда режет строку на несколько line)
    out.sort(key=lambda t: (round(t[1] / 3), t[0]))
    merged = []
    for t in out:
        if merged and abs(merged[-1][1] - t[1]) < 3:
            m = merged[-1]
            merged[-1] = (min(m[0], t[0]), min(m[1], t[1]), max(m[2], t[2]), max(m[3], t[3]), m[4] + " " + t[4], m[5] and t[5])
        else:
            merged.append(t)
    return merged


class Analysis:
    def __init__(self, pdf_path: Path, builder):
        self.doc = pymupdf.open(str(pdf_path))
        self.b = builder
        self.npages = len(self.doc)
        self.toc = self.doc.get_toc(simple=False)
        self.pages = {}        # hid -> page (1-based)
        self.ypos = {}         # hid -> y
        self.ok_outline = self._match_outline()
        self._lines_cache = {}

    def lines(self, pno):
        if pno not in self._lines_cache:
            self._lines_cache[pno] = _lines(self.doc[pno])
        return self._lines_cache[pno]

    def _match_outline(self) -> bool:
        ours = self.b.outline
        if len(ours) != len(self.toc):
            # сопоставляем по тексту, сколько получится
            pass
        j = 0
        for hid, text in ours:
            nt = _norm(text)[:25]
            while j < len(self.toc) and _norm(self.toc[j][1])[:25] != nt:
                j += 1
            if j >= len(self.toc):
                return False
            e = self.toc[j]
            self.pages[hid] = e[2]
            dest = e[3] if len(e) > 3 else {}
            to = dest.get("to") if isinstance(dest, dict) else None
            self.ypos[hid] = to.y if to is not None else TOP
            j += 1
        return True

    # ------------------------------------------------------------- таблицы

    def find_text_page(self, needle: str, start=0):
        for pno in range(start, self.npages):
            hits = self.doc[pno].search_for(needle)
            if hits:
                return pno, hits[0]
        return None, None

    def table_rows_on_page(self, pno, below_y, has_bottom=True):
        """Сколько строк таблицы на странице: горизонтальные линии ниже подписи.
        С нижней границей линий на одну больше, чем строк; у разрезанной части нижней границы нет."""
        ys = [y for y in _hlines(self.doc[pno]) if y > below_y]
        if not ys:
            return 0, None
        return (len(ys) - 1 if has_bottom else len(ys)), ys[-1]


def _caption_needle(cap_text: str) -> str:
    return cap_text.replace(" ", " ")[:40]


# ------------------------------------------------------------------ подсказки

def compute_hints(an: Analysis, hints: dict, final: bool):
    new = copy.deepcopy(hints)
    new["pages"] = dict(an.pages)
    warnings = []
    changed_struct = False

    # ---- таблицы (по одной структурной правке за проход, сверху вниз)
    for tkey, cap, number, nrows in an.b.tables:
        if changed_struct:
            break
        splits = list(new["table_splits"].get(tkey, []))
        needle = f"Таблица {number} –" if number else _caption_needle(cap)
        pno, rect = an.find_text_page(needle)
        if pno is None:
            continue
        fit, last_y = an.table_rows_on_page(pno, rect.y1, has_bottom=not splits)
        tb = an.b.table_meta[tkey]
        hdr = tb["header_rows_first"]
        part1 = (splits[0] if splits else nrows)
        data_fit = fit - hdr
        anchors = new.setdefault("table_anchor", {})
        anchor = (pno, round(rect.y1))
        if splits and anchors.get(tkey) and (anchors[tkey][0] != anchor[0] or abs(anchors[tkey][1] - anchor[1]) > 2):
            # подпись таблицы сдвинулась (изменился текст выше) — ёмкость первой части другая, считаем заново
            new["table_splits"][tkey] = []
            anchors.pop(tkey, None)
            changed_struct = True
            continue
        if data_fit < part1:                       # первая часть не влезает
            k = max(2, data_fit)
            if last_y is not None and BOTTOM - last_y < 3 and k > 2:
                k -= 1                             # запас на расхождение Word/LibreOffice
            new["table_splits"][tkey] = [k]
            anchors[tkey] = anchor
            changed_struct = True
            continue
        # продолжения
        start = pno + 1
        for i in range(len(splits)):
            cpno, crect = an.find_text_page(f"Продолжение таблицы {number}".strip(), start)
            if cpno is None:
                break
            cfit, _ = an.table_rows_on_page(cpno, crect.y1, has_bottom=(i == len(splits) - 1))
            hdr_c = tb["header_rows_cont"]
            end = splits[i + 1] if i + 1 < len(splits) else nrows
            chunk = end - splits[i]
            cdata = cfit - hdr_c
            if cdata < chunk:
                new["table_splits"][tkey] = splits[:i + 1] + [splits[i] + max(1, cdata - (1 if cdata > 3 else 0))]
                changed_struct = True
                break
            start = cpno + 1

    # «Тирасполь, ГГГГ» на титуле: подгоняем отступ, чтобы строка стояла у нижнего поля (верх строки ≈ 745 pt)
    city = f"{an.b.cfg.get('city', '')}, {an.b.cfg.get('year', '')}"
    target = 745.0
    cur = new.get("city_before", 120)
    hits = an.doc[0].search_for(city) if an.npages else []
    if hits:
        delta = target - hits[0].y0
        if abs(delta) > 2:
            new["city_before"] = max(0, round(cur + delta))
            changed_struct = True
    elif an.npages > 1 and an.doc[1].search_for(city):
        new["city_before"] = max(0, cur - 60)          # уехала на второй лист — поднимаем
        changed_struct = True

    if an.b.hid_ug and an.b.hid_ug[0] in an.pages:
        st = an.pages[an.b.hid_ug[0]]
        en = an.pages[an.b.hid_ug[1]] - 1 if an.b.hid_ug[1] in an.pages else an.npages
        new["ug_pages"] = en - st + 1
        if new.get("ug_pages") != hints.get("ug_pages"):
            changed_struct = True

    if changed_struct and not final:
        return new, warnings, True

    # ---- рисунок уехал на следующую страницу и оставил дыру: пробуем чуть уменьшить (до 70 %) (E7/C10)
    fs = new.setdefault("fig_scale", {})
    for pno in range(1, an.npages):
        page = an.doc[pno]
        imgs = [i for i in page.get_image_info() if i["bbox"][3] - i["bbox"][1] > 30]
        if not imgs:
            continue
        top = min(imgs, key=lambda i: i["bbox"][1])
        y0, y1 = top["bbox"][1], top["bbox"][3]
        if [l for l in an.lines(pno) if l[3] <= y0 + 1] or y0 > TOP + 30:
            continue
        cap = next((l[4] for l in an.lines(pno) if l[1] > y1 - 1), "")
        fid = an.b.figure_by_caption(cap)
        if fid is None:
            continue
        prev = an.doc[pno - 1]
        ys = [l[3] for l in an.lines(pno - 1)] + [i["bbox"][3] for i in prev.get_image_info()] + _hlines(prev)
        if not ys:
            continue
        gap = BOTTOM - max(ys)
        need_fixed = 13.8 + 4 + 13.8 + 2        # пустая строка, интервалы, подпись в одну строку
        h = y1 - y0
        scale = (gap - need_fixed) / h if h > 0 else 0
        cur = fs.get(fid, 1.0)
        if 0.7 <= scale < 1.0 and cur > 0.71:
            fs[fid] = max(0.7, round(cur * scale * 0.97, 3))
            changed_struct = True

    # ---- подраздел у низа страницы (B7)
    for hid, text in an.b.outline:
        lvl = an.b.outline_level.get(hid)
        if lvl not in (1, 2) or hid in new["break_before"]:
            continue
        pno = an.pages.get(hid)
        if not pno:
            continue
        y = an.ypos.get(hid, TOP)
        below = [l for l in an.lines(pno - 1) if l[1] > y + 2 and not l[5]]
        if len(below) < 3 and y > TOP + 100:
            new["break_before"].add(hid)
            changed_struct = True

    # ---- последняя строка абзаца из одного слова (C3)
    cond = new.setdefault("condense", {})
    body_from = an.pages.get(an.b.hid_intro, 1)
    body_to = an.pages.get(an.b.hid_concl_end, an.npages)
    norm_paras = [(pid, _norm(t)) for pid, t in an.b.paras]
    for pno in range(body_from - 1, min(body_to, an.npages)):
        ls = an.lines(pno)
        for i, l in enumerate(ls):
            words = l[4].split()
            if len(words) != 1 or l[0] > LEFT + 3 or i == 0:
                continue
            prev = ls[i - 1]
            if prev[2] < RIGHT - 15 or prev[0] < LEFT - 3:   # предыдущая строка не полная — это не хвост абзаца
                continue
            if l[5]:
                continue
            tail = _norm(l[4])
            ptail = _norm(prev[4])[-12:].rstrip("-")
            cands = [pid for pid, nt in norm_paras if nt.endswith(tail) and (ptail in nt)]
            if len(cands) != 1:
                continue
            pid = cands[0]
            lvl = cond.get(pid, 0)
            if lvl < 6:
                cond[pid] = 4 if lvl == 0 else 6
                changed_struct = True
            elif final:
                warnings.append(("C3", f"последняя строка абзаца из одного слова: «{l[4].strip()}»", pno + 1,
                                 "перефразируй предложение, чтобы в последней строке было 3–4 слова",
                                 an.b.para_src.get(pid)))
    return new, warnings, changed_struct


def final_warnings(an: Analysis, issues):
    b = an.b
    # рисунок в начале страницы (E7)
    for pno in range(an.npages):
        page = an.doc[pno]
        imgs = [i for i in page.get_image_info() if i["bbox"][3] - i["bbox"][1] > 30]
        if not imgs:
            continue
        top_img = min(imgs, key=lambda i: i["bbox"][1])
        y0 = top_img["bbox"][1]
        above = [l for l in an.lines(pno) if l[3] <= y0 + 1]
        if not above and y0 < TOP + 30:
            cap = next((l[4] for l in an.lines(pno) if l[1] > top_img["bbox"][3] - 1), "")
            fid = b.figure_by_caption(cap)
            issues.warn("E7", f"страница начинается с рисунка ({cap.strip()[:50]})", b.figure_src.get(fid),
                        "перенеси предложение, идущее после рисунка, в абзац перед ним — рисунок сдвинется вниз",
                        page=pno + 1)
    # задание должно уместиться на одном листе
    if an.npages > 2 and "АННОТАЦИЯ" not in an.doc[2].get_text()[:200]:
        issues.warn("K3", "задание не поместилось на один лист", None,
                    "сократи формулировки в task (diploma.yaml)", page=2)
    # большое пустое место (C10) в основной части
    start = an.pages.get(b.hid_intro, 1)
    end = an.pages.get(b.hid_concl_end, an.npages)
    h1_pages = {an.pages[h] for h, _ in b.outline if b.outline_level.get(h) == 0 and h in an.pages}
    for pno in range(start - 1, end - 1):
        if (pno + 2) in h1_pages:           # следующая страница начинается с новой главы
            continue
        page = an.doc[pno]
        ys = [l[3] for l in an.lines(pno)]
        ys += [i["bbox"][3] for i in page.get_image_info()]
        ys += _hlines(page)
        if not ys:
            continue
        gap = BOTTOM - max(ys)
        if gap > (BOTTOM - TOP) * 0.25:
            issues.warn("C10", f"внизу страницы пусто на {gap / (BOTTOM - TOP) * 100:.0f}% высоты", None,
                        "обычно это рисунок или таблица, не влезшие на страницу: сократи их или перенеси текст", page=pno + 1)
    # объём (J3)
    p = an.pages
    try:
        intro, ch1, concl, lst, bib = (p[b.hid_intro], p[b.hid_ch1], p[b.hid_concl], p[b.hid_abbr], p[b.hid_bib])
    except KeyError:
        return
    app = p.get(b.hid_app1)
    total = (app - 1) if app else an.npages
    intro_pages = ch1 - intro
    fill = _fill(an, ch1 - 2)
    if intro_pages > 2 or (intro_pages == 2 and fill > 0.98 and False):
        issues.warn("J3", f"введение занимает {intro_pages} стр., нужно 1–2", None, page=intro)
    elif intro_pages == 1 and fill < 0.8:
        issues.warn("J3", f"введение занимает {fill * 100:.0f}% страницы, нужны полные 1–2 страницы", None, page=intro)
    elif intro_pages == 2 and fill < 0.5:
        issues.warn("J3", f"вторая страница введения заполнена на {fill * 100:.0f}% — лучше полные страницы", None, page=intro + 1)
    concl_pages = lst - concl
    cfill = _fill(an, lst - 2)
    if concl_pages > 2:
        issues.warn("J3", f"заключение занимает {concl_pages} стр., нужно 1–2", None, page=concl)
    elif concl_pages == 1 and cfill < 0.8:
        issues.warn("J3", f"заключение занимает {cfill * 100:.0f}% страницы, нужны полные 1–2 страницы", None, page=concl)
    main = concl - ch1
    if not (47 <= main <= 65):
        issues.warn("J3", f"основная часть — {main} стр., по методичке 47–65", None)
    if not (50 <= total <= 70):
        issues.warn("J3", f"объём без приложений — {total} стр., по методичке 50–70", None)
    b.stats = {"pages_total": an.npages, "pages_no_app": total, "intro": intro_pages, "main": main,
               "conclusion": concl_pages}


def _fill(an, pno):
    if pno < 0 or pno >= an.npages:
        return 1.0
    ys = [l[3] for l in an.lines(pno)] + [i["bbox"][3] for i in an.doc[pno].get_image_info()]
    if not ys:
        return 0.0
    return (max(ys) - TOP) / (BOTTOM - TOP)


# ------------------------------------------------------------------ цикл

def layout_loop(pr, nb, issues, mc, out_path: Path, want_pdf=True, log=print):
    from .builder import Builder
    max_it = int((pr.cfg.get("layout") or {}).get("max_iterations", 8)) + 6
    hints = {"pages": {}, "table_splits": {}, "table_anchor": {}, "break_before": set(), "condense": {}}
    out_path = Path(out_path)
    work = Path(tempfile.mkdtemp(prefix="vkr_"))
    last = None
    t0 = time.time()
    for it in range(1, max_it + 1):
        b = Builder(pr, nb, issues, mc, hints)
        b.bib_order = pr.bib_order
        docx = work / "vkr.docx"
        b.build(docx)
        pdf = render_pdf(docx, work)
        an = Analysis(pdf, b)
        if not an.ok_outline:
            issues.warn("LAYOUT", "не удалось сопоставить заголовки с PDF — номера страниц в оглавлении могут быть неточны")
        new, _, changed = compute_hints(an, hints, final=False)
        pages_changed = new["pages"] != hints["pages"]
        log(f"  вёрстка, проход {it}: {an.npages} стр."
            + (" — правки" if changed else "") + (" — номера страниц" if pages_changed and not changed else ""))
        last = (b, an, pdf, docx)
        if os.environ.get("VKR_DEBUG"):
            for k in ("table_splits", "break_before", "condense", "ug_pages"):
                if new.get(k) != hints.get(k):
                    log(f"    {k}: {hints.get(k)} -> {new.get(k)}")
        if not changed and not pages_changed:
            break
        hints = new
    else:
        issues.warn("LAYOUT", f"вёрстка не сошлась за {max_it} проходов — проверь результат глазами")
    b, an, pdf, docx = last
    _, warns, _ = compute_hints(an, hints, final=True)
    for rule, msg, page, hint, src in warns:
        issues.warn(rule, msg, src, hint, page=page)
    final_warnings(an, issues)
    # руководство пользователя: «на N листах»
    shutil.copy(docx, out_path)
    pdf_out = None
    if want_pdf:
        pdf_out = out_path.with_suffix(".pdf")
        shutil.copy(pdf, pdf_out)
    log(f"  готово за {time.time() - t0:.0f} с")
    an.doc.close()
    shutil.rmtree(work, ignore_errors=True)
    return {"docx": out_path, "pdf": pdf_out, "pages": an.npages, "stats": getattr(b, "stats", {}),
            "builder": b}
