"""Перенос готового диплома из .docx в формат генератора (для проверки на дипломе Гончарука).

python tools/import_docx.py diploma.docx outdir/
"""
import re
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn

src, out = Path(sys.argv[1]), Path(sys.argv[2])
(out / "chapters").mkdir(parents=True, exist_ok=True)
(out / "appendix").mkdir(parents=True, exist_ok=True)
(out / "img").mkdir(parents=True, exist_ok=True)
d = docx.Document(str(src))
rels = d.part.rels


def ptext(el):
    return "".join(x.text or "" for x in el.iter(qn("w:t"))).replace(" ", " ")


def is_num(el):
    return el.find(".//" + qn("w:numPr")) is not None


def images(el):
    return [b.get(qn("r:embed")) for b in el.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")]


ABBR = set()


def sentence_case(t):
    words = t.split()
    out_w = []
    for k, w in enumerate(words):
        core = re.sub(r"[^\wА-Яа-яЁё]", "", w)
        if re.fullmatch(r"[A-Z0-9]+", core) or core in ABBR:
            out_w.append(w)
        else:
            out_w.append(w.lower() if k else w[:1] + w[1:].lower())
    return " ".join(out_w)


def esc(t):
    t = t.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`").replace("$", "\\$")
    return t


def refs(t):
    t = re.sub(r"(рисун\w*)\s+(\d+)\.(\d+)", r"\1 @fig:f\2_\3", t, flags=re.I)
    t = re.sub(r"(таблиц\w*)\s+(\d+)\.(\d+)", r"\1 @tbl:t\2_\3", t, flags=re.I)
    t = re.sub(r"(листинг\w*)\s+(\d+)\.(\d+)", r"\1 @lst:l\2_\3", t, flags=re.I)

    def cite(m):
        inner = m.group(1)
        mm = re.fullmatch(r"(\d+)\s*,\s*(с\.\s*.+)", inner)
        if mm:
            return f"[@s{mm.group(1)}, {mm.group(2)}]"
        nums = re.split(r"\s*[,;]\s*", inner)
        if all(n.isdigit() for n in nums):
            return "[" + "; ".join(f"@s{n}" for n in nums) + "]"
        return m.group(0)
    t = re.sub(r"\[([\d ,;с.\-–]+)\]", cite, t)
    return t


body = list(d.element.body.iterchildren())
items = []
for el in body:
    tag = el.tag.split("}")[1]
    if tag == "p":
        items.append(("p", el, ptext(el).strip()))
    elif tag == "tbl":
        items.append(("t", el, ""))

# --- аннотация
def find(text, start=0, exact=True):
    for i in range(start, len(items)):
        k, el, t = items[i]
        if k == "p" and (t == text if exact else t.startswith(text)):
            return i
    return None

ia, iab = find("АННОТАЦИЯ"), find("ABSTRACT")
itoc = find("ОГЛАВЛЕНИЕ")
ann_ru = "\n\n".join(t for k, _, t in items[ia + 1:iab] if k == "p" and t)
ann_en = "\n\n".join(t for k, _, t in items[iab + 1:itoc] if k == "p" and t)
iintro = find("ВВЕДЕНИЕ", itoc + 1)
ich1 = next(i for i in range(iintro, len(items)) if items[i][0] == "p" and re.match(r"^1\s+[А-ЯЁ]{3}", items[i][2]))
iconcl = find("ЗАКЛЮЧЕНИЕ", ich1)
iabbr = find("ПЕРЕЧЕНЬ", iconcl, exact=False)
ibib = find("СПИСОК ИСТОЧНИКОВ", iabbr)
iug = find("ОГЛАВЛЕНИЕ", ibib)

for k, el, t in items[iabbr + 1:ibib]:
    m = re.match(r"^(\S+)\s*[–-]\s*(.+?)[;.]?$", t)
    if m:
        ABBR.add(m.group(1))
abbrevs = {}
for k, el, t in items[iabbr + 1:ibib]:
    m = re.match(r"^(\S+)\s*[–-]\s*(.+?)[;.]?$", t)
    if m:
        abbrevs[m.group(1)] = m.group(2)

sources = []
for k, el, t in items[ibib + 1:(iug or len(items))]:
    if k == "p" and len(t) > 15:
        sources.append(re.sub(r"^\d+\.\s*", "", t))

imgn = 0


def convert(seq, ug=False):
    global imgn
    md = []
    pending_img = None
    pending_tcap = None
    i = 0
    while i < len(seq):
        k, el, t = seq[i]
        if k == "t":
            rows = el.findall(qn("w:tr"))
            cells0 = rows[0].findall(qn("w:tc")) if rows else []
            nxt = seq[i + 1][2] if i + 1 < len(seq) else ""
            if len(rows) == 1 and len(cells0) == 1 and nxt.startswith("Листинг"):
                lines = [ptext(p) for p in cells0[0].findall(qn("w:p"))]
                m = re.match(r"Листинг\s+([А-Я\d]+)\.(\d+)\s*–\s*(.+)", nxt)
                if m:
                    lab = f"l{m.group(1)}_{m.group(2)}" if m.group(1).isdigit() else f"la{m.group(2)}"
                    cap = m.group(3).strip()
                else:
                    lab, cap = "", nxt
                code = "\n".join(lines).rstrip()
                md.append(f'```csharp {{#lst:{lab} caption="{cap}"}}\n{code}\n```')
                i += 2
                continue
            if pending_tcap and rows:
                lab, cap = pending_tcap
                grid = []
                for r in rows:
                    line = []
                    for c in r.findall(qn("w:tc")):
                        tcPr = c.find(qn("w:tcPr"))
                        span, vm = 1, None
                        if tcPr is not None:
                            gs = tcPr.find(qn("w:gridSpan"))
                            if gs is not None:
                                span = int(gs.get(qn("w:val")))
                            v = tcPr.find(qn("w:vMerge"))
                            if v is not None:
                                vm = v.get(qn("w:val")) or "continue"
                        txt = "^" if vm == "continue" else esc(ptext(c)).replace("|", "\\|").strip()
                        line += [txt] + ["<"] * (span - 1)
                    grid.append(line)
                ncol = max(len(r) for r in grid)
                grid = [r + [""] * (ncol - len(r)) for r in grid]
                hdr = 1
                while hdr < len(grid) and "^" in grid[hdr]:
                    hdr += 1
                md.append(f"Таблица: {cap} {{#tbl:{lab}}}\n\n"
                          + "\n".join("| " + " | ".join(r) + " |" for r in grid[:hdr]) + "\n|" + "---|" * ncol + "\n"
                          + "\n".join("| " + " | ".join(r) + " |" for r in grid[hdr:]))
                pending_tcap = None
            i += 1
            continue
        ims = images(el)
        if ims:
            for rid in ims[:1]:
                part = rels[rid].target_part
                imgn += 1
                ext = Path(part.partname).suffix
                name = f"img/fig{imgn}{ext}"
                (out / name).write_bytes(part.blob)
                pending_img = name
            i += 1
            continue
        if not t:
            i += 1
            continue
        m = re.match(r"^Рисунок\s+([А-Я\d]+)\.(\d+)\s*[–-]?\s*(.*)$", t)
        if m and pending_img:
            lab = f"f{m.group(1)}_{m.group(2)}" if m.group(1).isdigit() else f"fa{m.group(2)}"
            cap = m.group(3).strip()
            md.append(f"![{esc(cap)}]({pending_img}){{#fig:{lab}}}")
            pending_img = None
            i += 1
            continue
        m = re.match(r"^Таблица\s+(\d+)\.(\d+)\s*[–-]\s*(.+)$", t)
        if m:
            pending_tcap = (f"t{m.group(1)}_{m.group(2)}", m.group(3).strip())
            i += 1
            continue
        if re.match(r"^Листинг\s+\S+\s*[–-]", t):
            i += 1
            continue
        m = re.match(r"^(\d+)\s+([А-ЯЁA-Z][А-ЯЁA-Z ,\-–()]+)$", t)
        if m and t.upper() == t:
            md.append("# " + sentence_case(m.group(2).strip()))
            i += 1
            continue
        m = re.match(r"^(\d+\.\d+)\.?\s+(.+)$", t)
        if m and not is_num(el) and len(t) < 160:
            md.append("## " + m.group(2).strip().rstrip("."))
            i += 1
            continue
        if ug and t in ("ВВЕДЕНИЕ", "ЗАКЛЮЧЕНИЕ"):
            md.append("# " + t.capitalize())
            i += 1
            continue
        if is_num(el):
            md.append("- " + refs(esc(t)))
            # список — без пустых строк между пунктами
            while i + 1 < len(seq) and seq[i + 1][0] == "p" and is_num(seq[i + 1][1]) and seq[i + 1][2]:
                i += 1
                md[-1] += "\n- " + refs(esc(seq[i][2]))
            i += 1
            continue
        md.append(refs(esc(t)))
        i += 1
    return "\n\n".join(md) + "\n"


(out / "chapters/intro.md").write_text(convert(items[iintro + 1:ich1]), encoding="utf-8")
body_md = convert(items[ich1:iconcl])
chs = re.split(r"(?m)^(?=# )", body_md)
files = []
for n, ch in enumerate([c for c in chs if c.strip()], 1):
    f = f"chapters/{n}.md"
    (out / f).write_text(ch, encoding="utf-8")
    files.append(f)
(out / "chapters/conclusion.md").write_text(convert(items[iconcl + 1:iabbr]), encoding="utf-8")
if iug:
    # пропускаем таблицу оглавления руководства
    j = iug + 1
    while items[j][0] == "t":
        j += 1
    (out / "appendix/user-guide.md").write_text(convert(items[j:], ug=True), encoding="utf-8")

import yaml
srcs = {f"s{n}": {"type": "other", "text": s, "checked": True} for n, s in enumerate(sources, 1)}
(out / "sources.yaml").write_text(yaml.safe_dump(srcs, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
cfg = {
    "year": 2026,
    "student": {"name": "Гончарук Иван Александрович", "group": "ИТ22ДР62ПИ"},
    "supervisor": {"name": "Кирсанова Алла Владимировна", "degree": "канд. пед. наук", "title": "доцент"},
    "task_head": {"name": "С.Г. Федорченко", "position": "зав. кафедрой ПОВТ", "degree": "канд. техн. наук", "title": "доцент"},
    "topic": "Разработка программной платформы для управления жизненным циклом данных и конфигурирования RAG",
    "order": {"number": "354-ОП", "date": "2026-03-17"},
    "deadline": "2026-06-12",
    "task": {"issued": "2026-03-17",
             "input_data": "техническая документация по разработке клиент-серверных приложений, руководство по API для обработки документов, нормативные акты в сфере информационной безопасности и защиты информации",
             "questions": "разработать программную платформу для управления жизненным циклом данных и конфигурирования RAG, включающую: систему загрузки и хранения документов, механизм обработки и индексирования данных, подсистему генерации эмбеддингов и семантического поиска, а также интерфейс для взаимодействия пользователя с системой",
             "extra": "расчёт себестоимости от внедрения результатов"},
    "annotation": {"ru": ann_ru, "en": ann_en},
    "abbreviations": abbrevs,
    "bibliography": {"order": "alphabetical"},
    "content": {"intro": "chapters/intro.md", "chapters": files, "conclusion": "chapters/conclusion.md",
                "appendices": [{"file": "appendix/user-guide.md", "kind": "user-guide"}] if iug else []},
}
(out / "diploma.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
print("ok", files, len(sources), "sources", imgn, "images")
