"""Сборка .docx из модели. Все параметры оформления — из RULES.md (М 3.1–3.6)."""
from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Mm, Pt

from .bib import format_source
from .model import (Bold, Cite, Code, Emph, Figure, Formula, Heading, ListBlock, Listing, Math, Paragraph, Ref,
                    Table, Text, Url, Where, plain)
from .numbering import format_cite
from .typo import NBSP, fix_text

TEXT_W_MM = 170.0
FONT = "Times New Roman"
MONO = "Courier New"
J = WD_ALIGN_PARAGRAPH
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]

LATIN_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s(«\"„/]))\.?[A-Za-z][A-Za-z0-9]*(?:[\-+#_/.'’&][A-Za-z0-9]+)*[+#]*"
    r"(?:\s+[A-Za-z][A-Za-z0-9]*(?:[\-+#_/.'’&][A-Za-z0-9]+)*[+#]*)*"
    r"|(?<![A-Za-z0-9.])[A-Za-z][A-Za-z0-9]*(?:[\-+#_/.'’&][A-Za-z0-9]+)*[+#]*"
    r"(?:\s+[A-Za-z][A-Za-z0-9]*(?:[\-+#_/.'’&][A-Za-z0-9]+)*[+#]*)*")


def is_marker(inl) -> bool:
    return plain(inl).strip() in ("<", "^")


def marker_of(row, c):
    if c >= len(row):
        return ""
    t = plain(row[c]).strip()
    return t if t in ("<", "^") else ""


def ru_date(d) -> str:
    if isinstance(d, str):
        try:
            d = dt.date.fromisoformat(d)
        except ValueError:
            return d
    return f"{d.day} {MONTHS[d.month - 1]} {d.year} г."


# ------------------------------------------------------------------ низкоуровневые XML-помощники

# порядок дочерних элементов по схеме OOXML: Word строго проверяет последовательность
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
             "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
             "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid",
             "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
             "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"]
RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
             "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w",
             "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign",
             "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"]
TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
               "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
               "tblCaption", "tblDescription"]
SETTINGS_ORDER = ["writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
                  "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
                  "printFractionalCharacterWidth", "printFormsData", "embedTrueTypeFonts", "embedSystemFonts",
                  "saveSubsetFonts", "saveFormsData", "mirrorMargins", "alignBordersAndEdges",
                  "bordersDoNotSurroundHeader", "bordersDoNotSurroundFooter", "gutterAtTop", "hideSpellingErrors",
                  "hideGrammaticalErrors", "activeWritingStyle", "proofState", "formsDesign", "attachedTemplate",
                  "linkStyles", "stylePaneFormatFilter", "stylePaneSortMethod", "documentType", "mailMerge",
                  "revisionView", "trackRevisions", "doNotTrackMoves", "doNotTrackFormatting", "documentProtection",
                  "autoFormatOverride", "styleLockTheme", "styleLockQFSet", "defaultTabStop", "autoHyphenation",
                  "consecutiveHyphenLimit", "hyphenationZone", "doNotHyphenateCaps", "showEnvelope",
                  "summaryLength", "clickAndTypeStyle", "defaultTableStyle", "evenAndOddHeaders",
                  "bookFoldRevPrinting", "bookFoldPrinting", "bookFoldPrintingSheets",
                  "drawingGridHorizontalSpacing", "drawingGridVerticalSpacing", "displayHorizontalDrawingGridEvery",
                  "displayVerticalDrawingGridEvery", "doNotUseMarginsForDrawingGridOrigin",
                  "drawingGridHorizontalOrigin", "drawingGridVerticalOrigin", "doNotShadeFormData", "noPunctuationKerning",
                  "characterSpacingControl", "printTwoOnOne", "strictFirstAndLastChars", "noLineBreaksAfter",
                  "noLineBreaksBefore", "savePreviewPicture", "doNotValidateAgainstSchema", "saveInvalidXml",
                  "ignoreMixedContent", "alwaysShowPlaceholderText", "doNotDemarcateInvalidXml", "saveXmlDataOnly",
                  "useXSLTWhenSaving", "saveThroughXslt", "showXMLTags", "alwaysMergeEmptyNamespace",
                  "updateFields", "hdrShapeDefaults", "footnotePr", "endnotePr", "compat", "docVars", "rsids",
                  "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping", "doNotIncludeSubdocsInStats",
                  "doNotAutoCompressPictures", "forceUpgrade", "captions", "readModeInkLockDown", "smartTagType",
                  "schemaLibrary", "shapeDefaults", "doNotEmbedSmartTags", "decimalSymbol", "listSeparator"]


def insert_ordered(parent, child, order):
    """Вставить child в parent с соблюдением порядка схемы; одноимённый элемент заменяется."""
    name = child.tag.split("}")[1]
    old = parent.find(qn("w:" + name))
    if old is not None:
        parent.replace(old, child)
        return child
    idx = order.index(name) if name in order else len(order)
    for k, ex in enumerate(list(parent)):
        en = ex.tag.split("}")[1]
        if en in order and order.index(en) > idx:
            ex.addprevious(child)
            return child
    parent.append(child)
    return child


def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), str(v))
    return e


def set_rfonts(rpr, name):
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = insert_ordered(rpr, _el("w:rFonts"), RPR_ORDER)
    for a in list(rf.attrib):
        del rf.attrib[a]
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name)


def set_lang(rpr, lang):
    lg = rpr.find(qn("w:lang"))
    if lg is None:
        lg = insert_ordered(rpr, _el("w:lang"), RPR_ORDER)
    lg.set(qn("w:val"), lang)


def ppr_set(p, tag, **attrs):
    ppr = p._p.get_or_add_pPr()
    e = ppr.find(qn(tag))
    if e is None:
        e = insert_ordered(ppr, _el(tag, **attrs), PPR_ORDER)
    else:
        for k, v in attrs.items():
            e.set(qn(k), str(v))
    return e


def set_outline(p, level):
    ppr_set(p, "w:outlineLvl", **{"w:val": level})


def no_hyphen(p):
    ppr_set(p, "w:suppressAutoHyphens")


def add_field(paragraph, instr):
    r = paragraph.add_run()
    b = _el("w:fldChar", **{"w:fldCharType": "begin"})
    r._r.append(b)
    r2 = paragraph.add_run()
    it = _el("w:instrText")
    it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    it.text = instr
    r2._r.append(it)
    r3 = paragraph.add_run()
    r3._r.append(_el("w:fldChar", **{"w:fldCharType": "separate"}))
    r4 = paragraph.add_run("1")
    r5 = paragraph.add_run()
    r5._r.append(_el("w:fldChar", **{"w:fldCharType": "end"}))


def tbl_borders(table, top=True, bottom=True, left=True, right=True, inside_h=True, inside_v=True, sz=4):
    tblPr = table._tbl.tblPr
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    b = _el("w:tblBorders")
    for name, on in (("top", top), ("left", left), ("bottom", bottom), ("right", right),
                     ("insideH", inside_h), ("insideV", inside_v)):
        if on:
            b.append(_el(f"w:{name}", **{"w:val": "single", "w:sz": sz, "w:space": 0, "w:color": "000000"}))
        else:
            b.append(_el(f"w:{name}", **{"w:val": "nil"}))
    insert_ordered(tblPr, b, TBLPR_ORDER)


def tbl_layout(table, widths_mm, center=True):
    tblPr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout", "w:jc", "w:tblInd"):
        e = tblPr.find(qn(tag))
        if e is not None:
            tblPr.remove(e)
    total = sum(widths_mm)
    insert_ordered(tblPr, _el("w:tblW", **{"w:w": int(total * 56.6929), "w:type": "dxa"}), TBLPR_ORDER)
    if center:
        insert_ordered(tblPr, _el("w:jc", **{"w:val": "center"}), TBLPR_ORDER)
    insert_ordered(tblPr, _el("w:tblLayout", **{"w:type": "fixed"}), TBLPR_ORDER)
    grid = table._tbl.tblGrid
    for k, gc in enumerate(grid.findall(qn("w:gridCol"))):
        gc.set(qn("w:w"), str(int(widths_mm[k] * 56.6929)))
    for row in table.rows:
        for k, cell in enumerate(row.cells):
            cell.width = Mm(widths_mm[k])


def row_flags(row, header=False, cant_split=True):
    trPr = row._tr.get_or_add_trPr()
    if cant_split:
        trPr.append(_el("w:cantSplit"))
    if header:
        trPr.append(_el("w:tblHeader"))


def cell_margins(table, top=0, bottom=0, left=0.19, right=0.19):
    tblPr = table._tbl.tblPr
    m = _el("w:tblCellMar")
    for side, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        m.append(_el(f"w:{side}", **{"w:w": int(v * 567), "w:type": "dxa"}))
    insert_ordered(tblPr, m, TBLPR_ORDER)


# ------------------------------------------------------------------ билдер

class Builder:
    def __init__(self, pr, nb, issues, math_cache, hints=None):
        self.pr = pr
        self.cfg = pr.cfg
        self.nb = nb
        self.issues = issues
        self.math = math_cache
        self.hints = hints or {}
        self.outline = []          # [(hid, text)] в порядке появления — для сопоставления с PDF
        self.paras = []            # [(pid, text)] абзацы основного текста — для правки последних строк
        self.tables = []           # [(tkey, caption_text, nrows)] таблицы
        self.figures = []          # [(caption_text)]
        self._hid = 0
        self._pid = 0
        self._tid = 0
        self.outline_level = {}
        self.para_src = {}
        self.figure_src = {}
        self.table_meta = {}
        self.hid_intro = self.hid_ch1 = self.hid_concl = self.hid_abbr = self.hid_bib = None
        self.hid_concl_end = self.hid_app1 = None
        self.hid_ug = None         # (hid метки приложения-руководства, hid следующего приложения | None)

    # ---------------------------------------------------------- стили и документ

    def _setup(self):
        d = Document()
        self.doc = d
        st = d.styles
        # docDefaults
        rpr_def = d.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
        set_rfonts(rpr_def, FONT)
        set_lang(rpr_def, "ru-RU")
        sz = rpr_def.find(qn("w:sz"))
        if sz is None:
            insert_ordered(rpr_def, _el("w:sz", **{"w:val": 28}), RPR_ORDER)
        else:
            sz.set(qn("w:val"), "28")
        normal = st["Normal"]
        normal.font.name = FONT
        normal.font.size = Pt(14)
        set_rfonts(normal.element.get_or_add_rPr(), FONT)
        # язык абзаца — явно в стиле: Word переносит слова только в тексте с языком, для которого есть словарь
        set_lang(normal.element.get_or_add_rPr(), "ru-RU")
        insert_ordered(normal.element.get_or_add_pPr(), _el("w:suppressAutoHyphens", **{"w:val": 0}), PPR_ORDER)
        pf = normal.paragraph_format
        pf.first_line_indent = Cm(1.25)
        pf.alignment = J.JUSTIFY
        pf.line_spacing = 1.5
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.widow_control = True

        def mk(name, size=14, bold=False, italic=False, align=J.JUSTIFY, ind=0.0, before=0, after=0, ls=1.5,
               keep=False, font=FONT, hyph=True, page_break=False):
            s = st.add_style(name, 1)
            s.base_style = normal
            s.font.size = Pt(size)
            s.font.bold = bold
            s.font.italic = italic
            s.font.name = font
            set_rfonts(s.element.get_or_add_rPr(), font)
            p = s.paragraph_format
            p.alignment = align
            p.first_line_indent = Cm(ind)
            p.left_indent = Cm(0)
            p.space_before = Pt(before)
            p.space_after = Pt(after)
            p.line_spacing = ls
            p.keep_with_next = keep
            p.widow_control = True
            p.page_break_before = page_break
            if not hyph:
                insert_ordered(s.element.get_or_add_pPr(), _el("w:suppressAutoHyphens"), PPR_ORDER)
            return s

        mk("VKR H1", bold=True, align=J.CENTER, after=20, keep=True, hyph=False, page_break=True)
        mk("VKR H2", bold=True, align=J.CENTER, before=12, after=8, keep=True, hyph=False)
        mk("VKR H3", bold=True, align=J.CENTER, before=12, after=8, keep=True, hyph=False)
        mk("VKR H4", italic=True, ind=1.25, keep=True)
        mk("VKR Caption", size=12, align=J.CENTER, ls=1.0, hyph=False)
        mk("VKR TableText", size=12, align=J.LEFT, ls=1.0, hyph=False)
        mk("VKR Listing", size=12, align=J.LEFT, ls=1.0, font=MONO, hyph=False)
        mk("VKR Spacer", size=12, align=J.LEFT, ls=1.0)
        mk("VKR Plain", align=J.LEFT, ls=1.0, hyph=False)
        mk("VKR Small", size=12, align=J.LEFT, ls=1.0, hyph=False)
        mk("VKR TOC", align=J.LEFT, ls=1.0, hyph=False)
        mk("VKR List", ind=1.25)

        # параметры страницы
        sec = d.sections[0]
        sec.page_width, sec.page_height = Mm(210), Mm(297)
        sec.left_margin, sec.right_margin = Mm(30), Mm(10)
        sec.top_margin, sec.bottom_margin = Mm(20), Mm(20)
        sec.footer_distance = Mm(7)
        sec.header_distance = Mm(10)

        # автоперенос, запрет переноса слов из прописных
        settings = d.settings.element
        # как в дипломе Гончарука: <w:autoHyphenation/> без атрибута (так пишет сам Word)
        insert_ordered(settings, _el("w:autoHyphenation"), SETTINGS_ORDER)
        insert_ordered(settings, _el("w:doNotHyphenateCaps"), SETTINGS_ORDER)
        # убираем наследие шаблона python-docx: восточноазиатские правила разбиения строк и японский язык темы
        for e in settings.iter(qn("w:useFELayout")):
            e.getparent().remove(e)
            break
        for e in settings.iter(qn("w:themeFontLang")):
            e.set(qn("w:val"), "ru-RU")
            for att in (qn("w:eastAsia"), qn("w:bidi")):
                if att in e.attrib:
                    del e.attrib[att]
        # Зона переноса 0, как в дипломе Гончарука: по умолчанию у Word зона 0,25" (6,35 мм), и он переносит
        # слово, только если в конце строки остаётся такая дыра — то есть почти никогда. У LibreOffice зона 0,
        # так что это ещё и сближает вёрстку Word и LibreOffice.
        insert_ordered(settings, _el("w:hyphenationZone", **{"w:val": 0}), SETTINGS_ORDER)
        # режим совместимости Word 2013+ (15), как у принятого диплома; в шаблоне python-docx — 14 (Word 2010)
        for cs in settings.iter(qn("w:compatSetting")):
            if cs.get(qn("w:name")) == "compatibilityMode":
                cs.set(qn("w:val"), "15")

    # ---------------------------------------------------------- inline

    def _resolve_ref(self, r: Ref) -> str:
        return self.nb.labels.get((r.kind, r.label), "??")

    def runs(self, p, inlines, italic_latin=True, italic=False, bold=False, size=None):
        for x in inlines:
            if isinstance(x, Text):
                self._text_runs(p, x.s, italic_latin, italic, bold, size)
            elif isinstance(x, Emph):
                self.runs(p, x.children, False, True, bold, size)
            elif isinstance(x, Bold):
                self.runs(p, x.children, italic_latin, italic, True, size)
            elif isinstance(x, Code):
                r = p.add_run(x.s)
                r.italic = True if italic_latin else italic
                r.bold = bold or None
                if size:
                    r.font.size = Pt(size)
                set_lang(r._r.get_or_add_rPr(), "en-US")
            elif isinstance(x, Url):
                r = p.add_run(x.s)
                r.italic = italic or None
                if size:
                    r.font.size = Pt(size)
                set_lang(r._r.get_or_add_rPr(), "en-US")
            elif isinstance(x, Math):
                om = self.math.get(x.tex)
                if om is None:
                    r = p.add_run(x.tex)
                    r.italic = True
                else:
                    p._p.append(om)
            elif isinstance(x, Ref):
                num = self._resolve_ref(x)
                if not num and p.runs:
                    p.runs[-1].text = p.runs[-1].text.rstrip(" " + NBSP)
                self._text_runs(p, num, False, italic, bold, size)
            elif isinstance(x, Cite):
                self._text_runs(p, format_cite(x, self.nb), False, italic, bold, size)

    def _text_runs(self, p, s, italic_latin, italic, bold, size):
        if not s:
            return
        segs = []
        if italic_latin and not italic:
            pos = 0
            for m in LATIN_RE.finditer(s):
                if m.start() > pos:
                    segs.append((s[pos:m.start()], False))
                segs.append((m.group(0), True))
                pos = m.end()
            if pos < len(s):
                segs.append((s[pos:], False))
        else:
            segs = [(s, False)]
        for t, lat in segs:
            r = p.add_run(t)
            if lat or italic:
                r.italic = True
            if bold:
                r.bold = True
            if size:
                r.font.size = Pt(size)
            if lat:
                set_lang(r._r.get_or_add_rPr(), "en-US")

    # ---------------------------------------------------------- абзацы

    def para(self, style=None, text=None, align=None, ind=None, before=None, after=None, ls=None, keep=None,
             page_break=None, bold=None, italic=None, size=None, left=None):
        p = self.doc.add_paragraph(style=style)
        f = p.paragraph_format
        if align is not None:
            f.alignment = align
        if ind is not None:
            f.first_line_indent = Cm(ind)
        if left is not None:
            f.left_indent = Cm(left)
        if before is not None:
            f.space_before = Pt(before)
        if after is not None:
            f.space_after = Pt(after)
        if ls is not None:
            f.line_spacing = ls
        if keep is not None:
            f.keep_with_next = keep
        if page_break is not None:
            f.page_break_before = page_break
        if text is not None:
            r = p.add_run(text)
            if bold:
                r.bold = True
            if italic:
                r.italic = True
            if size:
                r.font.size = Pt(size)
        return p

    def spacer(self):
        return self.para("VKR Spacer")

    def heading(self, text, style="VKR H1", outline=0, page_break=None, before=None, after=None, align=None,
                register=True):
        hid = None
        if register:
            self._hid += 1
            hid = f"h{self._hid}"
        if hid and hid in self.hints.get("break_before", set()):
            page_break = True
        p = self.para(style, page_break=page_break, before=before, after=after, align=align)
        lines = text.split("\n")
        for k, ln in enumerate(lines):
            r = p.add_run(ln)
            if k < len(lines) - 1:
                r.add_break()
        if outline is not None:
            set_outline(p, outline)
        if register:
            self.outline.append((hid, text.replace("\n", " ")))
            self.outline_level[hid] = outline
        return hid

    def figure_by_caption(self, cap_text):
        from .layout import _norm
        nc = _norm(cap_text)[:30]
        if not nc:
            return None
        hits = [k for k, c in enumerate(self.figures) if _norm(c)[:30] == nc]
        return f"f{hits[0] + 1}" if len(hits) == 1 else None

    def _condense(self, p, pid):
        lvl = self.hints.get("condense", {}).get(pid)
        if not lvl:
            return
        for r in p.runs:
            rpr = r._r.get_or_add_rPr()
            insert_ordered(rpr, _el("w:spacing", **{"w:val": -lvl}), RPR_ORDER)

    def body_para(self, inlines, italic_latin=True, src=None):
        self._pid += 1
        pid = f"p{self._pid}"
        p = self.para()
        self.runs(p, inlines, italic_latin)
        self._condense(p, pid)
        self.paras.append((pid, p.text))
        self.para_src[pid] = src
        return p

    # ---------------------------------------------------------- блоки

    def render_blocks(self, blocks, ctx="body"):
        prev = None
        for b in blocks:
            if isinstance(b, Heading):
                self.render_heading(b, ctx)
            elif isinstance(b, Paragraph):
                self.body_para(b.inlines, src=b.src)
            elif isinstance(b, ListBlock):
                self.render_list(b, 0)
            elif isinstance(b, Figure):
                self.render_figure(b)
            elif isinstance(b, Table):
                self.render_table(b)
            elif isinstance(b, Listing):
                self.render_listing(b, framed=(ctx != "appendix"))
            elif isinstance(b, Formula):
                self.render_formula(b)
            elif isinstance(b, Where):
                self.render_where(b)
            prev = b

    def render_heading(self, b: Heading, ctx):
        title = plain_resolved(b.inlines, self)
        title = fix_text(title, heading=True)
        if b.level == 4:
            p = self.para("VKR H4")
            self.runs(p, b.inlines, italic_latin=False, italic=True)
            return
        if b.kind == "special":
            self.heading(title.upper())
            return
        if b.kind == "appendix-sub":
            self.heading(title, "VKR H2", outline=None, register=False)
            return
        if b.level == 1:
            h = self.heading(f"{b.number}{NBSP}{title.upper()}" if b.number else title.upper())
            if ctx == "body" and self.hid_ch1 is None:
                self.hid_ch1 = h
        elif b.level == 2:
            self.heading(f"{b.number}{NBSP}{title}", "VKR H2", outline=1)
        else:
            self.heading(f"{b.number}{NBSP}{title}", "VKR H3", outline=2)

    def render_list(self, lb: ListBlock, depth):
        for k, it in enumerate(lb.items):
            if lb.style == "dash":
                marker = "-"
            elif lb.style == "dot":
                marker = f"{k + 1}."
            else:
                if depth == 0:
                    letters = "абвгдежзиклмнопрстуфхцчшщэюя"
                    marker = f"{letters[k % len(letters)]})"
                else:
                    marker = f"{k + 1})"
            self._pid += 1
            pid = f"p{self._pid}"
            p = self.para("VKR List", ind=1.25 + 0.75 * depth)
            p.add_run(marker + NBSP)
            self.runs(p, it.inlines)
            self._condense(p, pid)
            self.paras.append((pid, p.text))
            self.para_src[pid] = it.src
            for ch in it.children:
                self.render_list(ch, depth + 1)

    def _caption(self, word, number, caption, after=0, keep=False):
        p = self.para("VKR Caption", after=after, keep=keep)
        if number:
            p.add_run(f"{word} {number}" + (" – " if caption else ""))
        self.runs(p, caption, italic_latin=True)
        return p

    def render_figure(self, b: Figure):
        path = self.pr.path(b.path)
        self.spacer()
        p = self.para("VKR Plain", align=J.CENTER, keep=True)
        try:
            from PIL import Image
            w, h = Image.open(path).size
            frac = b.width or 1.0
            nat_mm = w * 25.4 / 96
            width_mm = min(TEXT_W_MM * frac, nat_mm)
            height_mm = width_mm * h / w
            if height_mm > 215:
                width_mm *= 215 / height_mm
            fid = f"f{len(self.figures) + 1}"
            width_mm *= self.hints.get("fig_scale", {}).get(fid, 1.0)
            p.add_run().add_picture(str(path), width=Mm(width_mm))
        except Exception:
            p.add_run(f"[нет рисунка: {b.path}]")
        cap = self._caption("Рисунок", b.number, b.caption)
        self.figures.append(cap.text)
        self.figure_src[f"f{len(self.figures)}"] = b.src
        self.spacer()

    def _col_widths(self, b: Table):
        ncol = len(b.header[0])
        weights = []
        last_hdr = b.header[-1]
        for c in range(ncol):
            cells = [last_hdr[c]] + [r[c] for r in b.rows if c < len(r)]
            cells = [x for x in cells if not is_marker(x)]
            longest_word = max((len(w) for cell in cells for w in plain(cell).split()), default=3)
            avg = sum(len(plain(cell)) for cell in cells) / max(1, len(cells))
            weights.append(max(math.sqrt(max(avg, 1)) * 3, longest_word * 0.9, 4))
        total = sum(weights)
        return [TEXT_W_MM * w / total for w in weights]

    def render_table(self, b: Table):
        self._tid += 1
        tkey = f"t{self._tid}"
        splits = self.hints.get("table_splits", {}).get(tkey, [])
        rows = b.rows
        bounds = [0] + list(splits) + [len(rows)]
        widths = self._col_widths(b)
        ncol = len(b.header[0])
        cap_text = None
        for part in range(len(bounds) - 1):
            first, last = part == 0, part == len(bounds) - 2
            if first:
                self.spacer()
                cap = self._caption("Таблица", b.number, b.caption, after=6, keep=True)
                cap_text = cap.text
            else:
                self.para("VKR Caption", text=f"Продолжение таблицы {b.number}".strip(), after=6, keep=True,
                          page_break=True)
            chunk = rows[bounds[part]:bounds[part + 1]]
            numbers = [[Text(str(k + 1))] for k in range(ncol)]
            if b.numbered_header:
                header = b.header + [numbers] if first else [numbers]
            else:
                header = b.header
            self._emit_table(header, chunk, widths, b, bottom=last)
            if last:
                self.spacer()
        self.tables.append((tkey, cap_text or "", b.number, len(rows)))
        self.table_meta[tkey] = {"header_rows_first": len(b.header) + (1 if b.numbered_header else 0),
                                 "header_rows_cont": 1 if b.numbered_header else len(b.header)}

    def _emit_table(self, header, rows, widths, b, bottom=True):
        ncol = len(header[0])
        grid = header + rows
        t = self.doc.add_table(rows=len(grid), cols=ncol)
        tbl_layout(t, widths)
        tbl_borders(t, bottom=bottom)
        cell_margins(t)
        al = {"left": J.LEFT, "center": J.CENTER, "right": J.RIGHT}
        nh = len(header)
        for r, row in enumerate(grid):
            tr = t.rows[r]
            is_head = r < nh
            row_flags(tr, header=is_head)
            for c in range(ncol):
                inl = row[c] if c < len(row) else []
                p = tr.cells[c].paragraphs[0]
                p.style = self.doc.styles["VKR TableText"]
                if is_head:
                    p.paragraph_format.alignment = J.CENTER
                else:
                    p.paragraph_format.alignment = al.get(b.align[c] if c < len(b.align) else "left", J.LEFT)
                # шапка и первая строка данных не отрываются друг от друга
                p.paragraph_format.keep_with_next = is_head or r == nh
                if not is_marker(inl):
                    self.runs(p, inl, italic_latin=True)
        # объединение ячеек: «<» — с левой, «^» — с верхней
        done = set()
        for r in range(len(grid)):
            for c in range(ncol):
                if (r, c) in done or is_marker(grid[r][c] if c < len(grid[r]) else []):
                    continue
                c1 = c
                while c1 + 1 < ncol and marker_of(grid[r], c1 + 1) == "<":
                    c1 += 1
                r1 = r
                while r1 + 1 < len(grid) and all(marker_of(grid[r1 + 1], k) == "^" for k in range(c, c1 + 1)):
                    r1 += 1
                if (r1, c1) != (r, c):
                    t.cell(r, c).merge(t.cell(r1, c1))
                    for rr in range(r, r1 + 1):
                        for cc in range(c, c1 + 1):
                            done.add((rr, cc))
        # высота строки ≥ 12 pt
        for tr in t.rows:
            trPr = tr._tr.get_or_add_trPr()
            trPr.append(_el("w:trHeight", **{"w:val": 240, "w:hRule": "atLeast"}))
        return t

    def render_listing(self, b: Listing, framed=True):
        """Рамка — границами абзацев: соседние абзацы с одинаковыми границами Word и LibreOffice
        сливают в одну рамку, а «не отрывать от следующего» надёжно держит листинг вместе с подписью."""
        lines = b.code.split("\n") or [""]
        if framed:
            self.spacer()
        for ln in lines:
            p = self.para("VKR Listing", keep=True if framed else None)
            if framed:
                f = p.paragraph_format
                f.left_indent = Cm(0.15)
                f.right_indent = Cm(0.15)
                ppr = p._p.get_or_add_pPr()
                bdr = _el("w:pBdr")
                for side in ("top", "left", "bottom", "right"):
                    bdr.append(_el(f"w:{side}", **{"w:val": "single", "w:sz": 4, "w:space": 3, "w:color": "000000"}))
                insert_ordered(ppr, bdr, PPR_ORDER)
            r = p.add_run(ln if ln else " ")
            set_lang(r._r.get_or_add_rPr(), "en-US")
        if framed:
            cap = self._caption("Листинг", b.number, b.caption)
            cap.paragraph_format.space_before = Pt(3)
            self.spacer()
        elif b.caption:
            self._caption("Листинг", b.number, b.caption)

    def render_formula(self, b: Formula):
        self.spacer()
        p = self.para("VKR Plain", ind=0, ls=1.0, keep=True)
        tabs = p.paragraph_format.tab_stops
        from docx.enum.text import WD_TAB_ALIGNMENT
        tabs.add_tab_stop(Mm(TEXT_W_MM / 2), WD_TAB_ALIGNMENT.CENTER)
        tabs.add_tab_stop(Mm(TEXT_W_MM), WD_TAB_ALIGNMENT.RIGHT)
        p.add_run("\t")
        om = self.math.get(b.tex)
        if om is None:
            r = p.add_run(b.tex)
            r.italic = True
        else:
            p._p.append(om)
        p.add_run("\t" + (f"({b.number})" if b.number else ""))
        self.spacer()

    def render_where(self, b: Where):
        for k, ln in enumerate(b.lines):
            p = self.para(ind=0, left=0 if k == 0 else 0.95, align=J.LEFT)
            if k == 0:
                p.add_run("где ")
            self.runs(p, ln)

    # ---------------------------------------------------------- части документа

    def title_page(self):
        c = self.cfg
        for ln in c["organization"]:
            self.para("VKR Small", ln, align=J.CENTER)
        head = c.get("head") or {}
        self.para("VKR Small", "", after=36)
        left = 10.7
        self.para("VKR Small", "Допустить к защите", left=left)
        self.para("VKR Small", f"{head.get('position', '')},", left=left)
        self.para("VKR Small", f"{head.get('degree', '')}, {head.get('title', '')}", left=left)
        p = self.para("VKR Small", head.get("name", ""), align=J.RIGHT)
        p.paragraph_format.right_indent = Cm(1.1)
        self.para("VKR Small", f"«____» _______________ {c['year']} г.", left=left)
        self.para("VKR Small", "", before=60)
        self.para("VKR Small", "ВЫПУСКНАЯ КВАЛИФИКАЦИОННАЯ РАБОТА", align=J.CENTER, bold=True, size=16, after=18)
        topic = c["topic"]
        p = self.para("VKR Small", align=J.CENTER, after=18)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run("тема: «")
        r.bold = True
        r.font.size = Pt(18)
        chunks = [fix_text(x.strip(), heading=True).upper() for x in topic.split("|")]
        for k, ch in enumerate(chunks):
            r = p.add_run(ch)
            r.bold = True
            r.font.size = Pt(18)
            if k < len(chunks) - 1:
                r.add_break()
        r = p.add_run("»")
        r.bold = True
        r.font.size = Pt(18)
        self.para("VKR Small", c.get("work_kind", "БАКАЛАВРСКАЯ РАБОТА"), align=J.CENTER, after=30)
        self.para("VKR Small", f"Направление {c['direction']}", align=J.CENTER)
        self.para("VKR Small", f"Профиль: {c['profile_name']}", align=J.CENTER, after=48)
        st, sv = c["student"], c["supervisor"]
        sname = st["name"].split()
        vname = sv["name"].split()
        self._two_col([("Студент", sname[0]), (f"группы {st['group']}", " ".join(sname[1:]))], after=24, indent=17)
        self._two_col([("Научный руководитель,", vname[0]),
                       (f"{sv['degree']}, {sv['title']}", " ".join(vname[1:]))], indent=17)
        # «Тирасполь, ГГГГ» — обычный абзац текста внизу листа. Отступ сверху подбирает цикл вёрстки
        # (hints["city_before"]), чтобы строка встала у нижнего поля с запасом ~1,5 см.
        sec = self.doc.sections[0]
        sec.footer.is_linked_to_previous = False
        self.para("VKR Small", f"{c['city']}, {c['year']}", align=J.CENTER,
                  before=self.hints.get("city_before", 120))

    def _two_col(self, rows, after=0, style="VKR Small", indent=0):
        t = self.doc.add_table(rows=len(rows), cols=2)
        tbl_layout(t, [106, 47] if indent else [105, 65], center=False)
        if indent:
            insert_ordered(t._tbl.tblPr, _el("w:tblInd", **{"w:w": int(indent * 56.69), "w:type": "dxa"}), TBLPR_ORDER)
        tbl_borders(t, False, False, False, False, False, False)
        for k, (a, b) in enumerate(rows):
            for c, txt in enumerate((a, b)):
                p = t.rows[k].cells[c].paragraphs[0]
                p.style = self.doc.styles["VKR Small"]
                p.add_run(txt)
        if after:
            self.para("VKR Spacer", after=0).paragraph_format.space_after = Pt(after - 12 if after > 12 else 0)

    def task_page(self):
        c = self.cfg
        tsec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        tsec.footer.is_linked_to_previous = False
        p = self.para("VKR Small")
        p.add_run(c["organization"][0])
        p.alignment = J.CENTER
        for ln in c["organization"][1:]:
            self.para("VKR Small", ln, align=J.CENTER)
        head = c.get("task_head") or c.get("head") or {}
        self.para("VKR Small", "", after=12)
        left = 11.0
        self.para("VKR Small", "Утверждаю", left=left)
        self.para("VKR Small", f"{head.get('position', '')},", left=left)
        self.para("VKR Small", f"{head.get('degree', '')}, {head.get('title', '')}", left=left)
        self.para("VKR Small", head.get("name", ""), align=J.RIGHT)
        self.para("VKR Small", f"«____» __________ {c['year']} г.", left=left, after=18)
        self.para("VKR Plain", "ЗАДАНИЕ", align=J.CENTER, bold=True, ls=1.5)
        self.para("VKR Plain", "НА ВЫПУСКНУЮ КВАЛИФИКАЦИОННУЮ РАБОТУ БАКАЛАВРА", align=J.CENTER, bold=True, ls=1.5)
        task = c.get("task") or {}
        st = c["student"]
        dative = st.get("name_dative") or dative_name(st["name"])

        def lab(label, value, italic=True):
            p = self.para()
            r = p.add_run(label + " ")
            r.bold = True
            if value:
                r2 = p.add_run(value)
                r2.italic = italic
            return p

        lab("Студенту", dative)
        lab("Тема ВКР:", f"«{fix_text(c['topic'].replace('|', ' '))}»")
        order = c.get("order") or {}
        self.para(text=f"утверждена приказом по университету № {order.get('number', '_____')} от "
                       f"{ru_date(order['date']) if order.get('date') else '«___» ___________ ' + str(c['year']) + ' г.'}")
        self.para(text="Срок сдачи расчетно-пояснительной записки на кафедру "
                       + (ru_date(c["deadline"]) if c.get("deadline") else f"«___» ______ {c['year']} г."))
        def dot(v):
            v = fix_text(str(v or "").strip())
            return v if not v or v.endswith(".") else v + "."
        lab("Исходные данные к работе:", dot(task.get("input_data")))
        lab("Перечень подлежащих разработке вопросов:", dot(task.get("questions")))
        lab("Перечень дополнительных вопросов:", dot(task.get("extra")))
        self.para(text="Дата выдачи задания " + (ru_date(task["issued"]) if task.get("issued") else
                                                f"«____» ________ {c['year']} г."), before=6, ind=0)
        sv = c["supervisor"]
        # подписи в одну колонку: линии и ФИО начинаются от одной табуляции (как у Гончарука)
        lab_sv = f"Научный руководитель, {sv['degree']}, {sv['title']}"
        lab_st = "Задание принял к исполнению"
        tab_mm = min(max(text_width_mm(lab_sv, 14), text_width_mm(lab_st, 14)) + 2, TEXT_W_MM - 60)
        from docx.enum.text import WD_TAB_ALIGNMENT
        for lab_text, who in ((lab_sv, sv["name"]), (lab_st, st["name"])):
            p = self.para(ind=0, align=J.LEFT)
            p.paragraph_format.tab_stops.add_tab_stop(Mm(tab_mm), WD_TAB_ALIGNMENT.LEFT)
            p.add_run(f"{lab_text}\t___________/{short_name(who)}/")

    def annotation_page(self):
        c = self.cfg
        self.heading("АННОТАЦИЯ", register=False, outline=None)
        from .typo import apply_inlines
        from .inline import parse_inline
        for par in [x.strip() for x in re.split(r"\n\s*\n", c["annotation"]["ru"].strip()) if x.strip()]:
            inl = parse_inline(" ".join(par.split()))
            apply_inlines(inl)
            self.body_para(inl)
        self.heading("ABSTRACT", register=False, outline=None, page_break=False, before=24)
        for par in [x.strip() for x in re.split(r"\n\s*\n", c["annotation"]["en"].strip()) if x.strip()]:
            p = self.para()
            p.add_run(" ".join(par.split()).replace(" - ", " – "))
            for r in p.runs:
                set_lang(r._r.get_or_add_rPr(), "en-US")

    def toc(self, entries, title="ОГЛАВЛЕНИЕ"):
        """entries: [(level, number, title, hid)]"""
        self.heading(title, register=False, outline=None)
        pages = self.hints.get("pages", {})
        t = self.doc.add_table(rows=len(entries), cols=3)
        tbl_layout(t, [12, 146, 12], center=False)
        tbl_borders(t, False, False, False, False, False, False)
        cell_margins(t, left=0.05, right=0.05)
        for k, (lvl, num, text, hid) in enumerate(entries):
            row = t.rows[k]
            pg = str(pages.get(hid, "00"))
            if lvl == 1:
                a = row.cells[0].merge(row.cells[1])
                p = a.paragraphs[0]
                p.style = self.doc.styles["VKR TOC"]
                p.paragraph_format.space_before = Pt(6)
                p.add_run(f"{num} {text}".strip() if num else text)
            else:
                p0 = row.cells[0].paragraphs[0]
                p0.style = self.doc.styles["VKR TOC"]
                p0.paragraph_format.left_indent = Cm(0.4)
                p0.add_run(num)
                p = row.cells[1].paragraphs[0]
                p.style = self.doc.styles["VKR TOC"]
                p.add_run(text)
            pp = row.cells[2].paragraphs[0]
            pp.style = self.doc.styles["VKR TOC"]
            pp.alignment = J.RIGHT
            if lvl == 1:
                pp.paragraph_format.space_before = Pt(6)
            pp.add_run(pg)
            # номер страницы — по нижней строке многострочного пункта
            tcPr = row.cells[2]._tc.get_or_add_tcPr()
            tcPr.append(_el("w:vAlign", **{"w:val": "bottom"}))
            row_flags(row)

    # ---------------------------------------------------------- сборка целиком

    def build(self, out_path):
        self._setup()
        c = self.cfg
        pr = self.pr
        self.title_page()
        self.task_page()
        # секция 2: нумерация видна
        new = self.doc.add_section(WD_SECTION.NEW_PAGE)
        new.footer.is_linked_to_previous = False
        fp = new.footer.paragraphs[0]
        fp.style = self.doc.styles["VKR Small"]
        fp.alignment = J.RIGHT
        add_field(fp, "PAGE")
        self.annotation_page()

        depth = int(c.get("toc_depth", 2))
        entries = []
        # заголовки оглавления создаём заранее: hid совпадут, т.к. порядок фиксирован
        plan = self._plan_outline(depth)
        self.toc(plan)

        # введение
        self.hid_intro = self.heading("ВВЕДЕНИЕ")
        if pr.intro:
            self.render_blocks(pr.intro.blocks)
        if pr.body:
            self.render_blocks(pr.body.blocks)
        self.hid_concl = self.heading("ЗАКЛЮЧЕНИЕ")
        if pr.conclusion:
            self.render_blocks(pr.conclusion.blocks)
        self.hid_abbr = self.hid_concl_end = self.heading("ПЕРЕЧЕНЬ УСЛОВНЫХ ОБОЗНАЧЕНИЙ, СИМВОЛОВ,\nЕДИНИЦ И ТЕРМИНОВ")
        ab = c.get("abbreviations") or {}
        from .bib import sort_key
        for k in sorted(ab, key=lambda x: sort_key({"type": "other", "text": str(x)})):
            p = self.para(ind=0, align=J.LEFT)
            self._text_runs(p, f"{k} – {str(ab[k]).rstrip('.')}.", True, False, False, None)
        self.hid_bib = self.heading("СПИСОК ИСТОЧНИКОВ")
        acc = c.get("defaults", {}).get("accessed") if isinstance(c.get("defaults"), dict) else None
        for key in self.bib_order:
            s = pr.sources[key]
            p = self.para()
            p.add_run(f"{self.nb.cite_num[key]}. {format_source(s, acc)}")
        for app in pr.appendices:
            self.render_appendix(app)
        self.doc.save(out_path)
        return out_path

    def _plan_outline(self, depth):
        """Список пунктов оглавления с hid, которые получат заголовки при рендере."""
        pr = self.pr
        # моделируем нумерацию hid так же, как она пойдёт при рендере
        hid = self._hid
        out = []

        def nxt():
            nonlocal hid
            hid += 1
            return f"h{hid}"

        out.append((1, "", "ВВЕДЕНИЕ", nxt()))
        for b in (pr.body.blocks if pr.body else []):
            if isinstance(b, Heading) and b.level <= 3:
                h = nxt()
                t = fix_text(plain_resolved(b.inlines, self), heading=True)
                if b.level == 1:
                    out.append((1, b.number, t.upper(), h))
                elif b.level <= depth:
                    out.append((b.level, b.number, t, h))
        out.append((1, "", "ЗАКЛЮЧЕНИЕ", nxt()))
        out.append((1, "", "ПЕРЕЧЕНЬ УСЛОВНЫХ ОБОЗНАЧЕНИЙ, СИМВОЛОВ, ЕДИНИЦ И ТЕРМИНОВ", nxt()))
        out.append((1, "", "СПИСОК ИСТОЧНИКОВ", nxt()))
        for app in pr.appendices:
            out.append((1, "", f"ПРИЛОЖЕНИЕ {app.letter} – {app.title.upper()}", nxt()))
            # заголовки внутри приложения тоже получат hid — пропускаем их
            hid += self._appendix_heading_count(app)
        return out

    def _appendix_heading_count(self, app):
        n = 0
        if app.kind == "user-guide":
            for b in app.blocks:
                if isinstance(b, Heading) and b.level <= 3:
                    n += 1
        return n

    def render_appendix(self, app):
        h = self.heading(f"ПРИЛОЖЕНИЕ {app.letter}", "VKR H1", outline=0, align=J.RIGHT, after=0)
        if self.hid_app1 is None:
            self.hid_app1 = h
        if self.hid_ug and self.hid_ug[1] is None:
            self.hid_ug = (self.hid_ug[0], h)
        if app.kind == "user-guide":
            self.hid_ug = (h, None)
        p = self.doc.paragraphs[-1]
        for r in p.runs:
            r.bold = False
        if app.kind == "user-guide":
            self._ug_title(app)
            entries = []
            hid = self._hid
            for b in app.blocks:
                if isinstance(b, Heading) and b.level <= 3:
                    hid += 1
                    t = fix_text(plain_resolved(b.inlines, self), heading=True)
                    if b.kind == "special":
                        entries.append((1, "", t.upper(), f"h{hid}"))
                    elif b.level == 1:
                        entries.append((1, b.number, t.upper(), f"h{hid}"))
                    elif b.level == 2:
                        entries.append((2, b.number, t, f"h{hid}"))
            self.toc(entries)
            self.render_blocks(app.blocks, ctx="user-guide")
        else:
            self.para("VKR H1", app.title.upper(), page_break=False, align=J.CENTER, after=20)
            self.render_blocks(app.blocks, ctx="appendix")

    def _ug_title(self, app):
        c = self.cfg
        for ln in c["organization"]:
            self.para("VKR Small", ln, align=J.CENTER)
        self.para("VKR Small", "", before=150)
        self.para("VKR Small", "ВЫПУСКНАЯ КВАЛИФИКАЦИОННАЯ РАБОТА", align=J.CENTER, bold=True, size=16, after=18)
        p = self.para("VKR Small", align=J.CENTER, after=18)
        r = p.add_run("тема: «" + " ".join(fix_text(x.strip(), heading=True).upper() for x in c["topic"].split("|")) + "»")
        r.bold = True
        r.font.size = Pt(18)
        self.para("VKR Small", c.get("work_kind", "БАКАЛАВРСКАЯ РАБОТА"), align=J.CENTER, after=30)
        self.para("VKR Small", f"Направление {c['direction']}", align=J.CENTER)
        self.para("VKR Small", f"Профиль: {c['profile_name']}", align=J.CENTER, after=24)
        self.para("VKR Small", app.title, align=J.CENTER, after=24)
        sheets = self.hints.get("ug_pages", "____")
        for ln in ("Эксплуатационный документ", "в текстовом виде", f"на {sheets} листах"):
            self.para("VKR Small", ln, align=J.CENTER)
        self.para("VKR Small", "", after=36)
        st = self.cfg["student"]
        sname = st["name"].split()
        self._two_col([("Студент", sname[0]), (f"группы {st['group']}", " ".join(sname[1:]))])


def plain_resolved(inlines, builder) -> str:
    out = []
    for x in inlines:
        if isinstance(x, Text):
            out.append(x.s)
        elif isinstance(x, (Emph, Bold)):
            out.append(plain_resolved(x.children, builder))
        elif isinstance(x, (Code, Url)):
            out.append(x.s)
        elif isinstance(x, Math):
            out.append(x.tex)
        elif isinstance(x, Ref):
            out.append(builder._resolve_ref(x))
        elif isinstance(x, Cite):
            out.append(format_cite(x, builder.nb))
    return "".join(out)


_FONT_CACHE = {}


def text_width_mm(text: str, size_pt: float) -> float:
    """Ширина строки в Times New Roman (или метрически совместимом Liberation Serif)."""
    try:
        from PIL import ImageFont
        if size_pt not in _FONT_CACHE:
            import subprocess
            path = ""
            for fam in ("Times New Roman", "Liberation Serif"):
                r = subprocess.run(["fc-match", "-f", "%{file}", fam], capture_output=True, text=True)
                if r.returncode == 0 and r.stdout and ("Times" in r.stdout or "Liberation" in r.stdout):
                    path = r.stdout
                    break
            _FONT_CACHE[size_pt] = ImageFont.truetype(path, int(size_pt * 10)) if path else None
        f = _FONT_CACHE[size_pt]
        if f is not None:
            return f.getlength(text) / 10 * 25.4 / 72
    except Exception:
        pass
    return len(text) * size_pt * 0.45 * 25.4 / 72


def short_name(full: str) -> str:
    """'Гончарук Иван Александрович' -> 'И.А. Гончарук'"""
    p = full.split()
    if len(p) >= 3:
        return f"{p[1][0]}.{p[2][0]}. {p[0]}"
    if len(p) == 2:
        return f"{p[1][0]}. {p[0]}"
    return full


def dative_name(full: str) -> str:
    try:
        from pytrovich.enums import Case, Gender, NamePart
        from pytrovich.maker import PetrovichDeclinationMaker
    except ImportError:
        return full
    p = full.split()
    if len(p) != 3:
        return full
    g = Gender.FEMALE if p[2].endswith(("вна", "чна", "кызы")) else Gender.MALE
    m = PetrovichDeclinationMaker()
    return " ".join([m.make(NamePart.LASTNAME, g, Case.DATIVE, p[0]),
                     m.make(NamePart.FIRSTNAME, g, Case.DATIVE, p[1]),
                     m.make(NamePart.MIDDLENAME, g, Case.DATIVE, p[2])])
