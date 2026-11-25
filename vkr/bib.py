"""Библиографическое описание по ГОСТ Р 7.0.11-2011 в варианте примеров методички."""
from __future__ import annotations

import datetime as dt
import re

DASH = " – "
CITIES = {"москва": "М.", "санкт-петербург": "СПб.", "ленинград": "Л.", "киев": "К.", "минск": "Мн.",
          "ростов-на-дону": "Ростов н/Д"}


def is_latin(s: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", s or "")
    if not letters:
        return False
    lat = sum(1 for c in letters if c.isascii())
    return lat > len(letters) / 2


def _author(a: str):
    """'Шляндин В.М.' | 'Шляндин, В.М.' | 'Martin R. C.' -> (surname, initials)"""
    a = a.strip()
    if "," in a:
        s, i = a.split(",", 1)
    else:
        bits = a.split(None, 1)
        s, i = bits[0], (bits[1] if len(bits) > 1 else "")
    i = i.strip()
    return s.strip(), i


def head_author(a):           # Шляндин, В.М.
    s, i = _author(a)
    return f"{s}, {i}" if i else s


def resp_author(a):           # В.М. Шляндин
    s, i = _author(a)
    return f"{i} {s}" if i else s


def _resp(authors, latin):
    if len(authors) >= 4:
        return resp_author(authors[0]) + (" [et al.]" if latin else " [и др.]")
    return ", ".join(resp_author(a) for a in authors)


def _date(d) -> str:
    if isinstance(d, (dt.date, dt.datetime)):
        return d.strftime("%d.%m.%Y")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(d))
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return str(d)


def _city(c):
    return CITIES.get(str(c).strip().lower(), str(c).strip())


def _end(s: str) -> str:
    s = s.rstrip()
    return s if s.endswith((".", "?", "!")) else s + "."


def _title(s):
    t = str(s["title"]).strip().rstrip(".")
    if s.get("kind"):
        t += f": {s['kind']}"
    return t


def _lead(s, latin):
    """Заголовок описания + область ответственности."""
    authors = s.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    title = _title(s)
    if 1 <= len(authors) <= 3:
        return f"{head_author(authors[0])} {title} / {_resp(authors, latin)}"
    if authors:
        return f"{title} / {_resp(authors, latin)}"
    return title


def format_source(s: dict, default_accessed=None) -> str:
    t = s.get("type", "book")
    if t == "other":
        return _end(str(s["text"]).strip())
    latin = is_latin(str(s.get("title", "")))
    pages_word = "p." if latin else "с."
    if t == "book" or t == "thesis":
        out = _lead(s, latin)
        if t == "thesis" and s.get("degree_work"):
            out = out.replace(" / ", f" : {s['degree_work']} / ", 1)
        if s.get("edition"):
            out += DASH.rstrip() + " " + str(s["edition"]).rstrip(".")
            out = ". – ".join(out.rsplit(" – ", 1))
        imprint = _city(s["city"]) if s.get("city") else ""
        if s.get("publisher"):
            imprint += f": {s['publisher']}"
        if s.get("year"):
            imprint += f", {s['year']}" if imprint else str(s["year"])
        out += f". – {imprint}"
        if s.get("pages"):
            out += f". – {s['pages']} {pages_word}"
        return _end(out)
    if t == "article":
        out = _lead(s, latin) + f" // {str(s['journal']).rstrip('.')}. – {s['year']}"
        vol = []
        if s.get("volume"):
            vol.append(f"{'Vol.' if latin else 'Т.'} {s['volume']}")
        if s.get("issue"):
            vol.append(f"№ {s['issue']}")
        if vol:
            out += ". – " + ", ".join(vol)
        if s.get("range"):
            out += f". – {'P.' if latin else 'С.'} {s['range']}"
        return _end(out)
    if t == "web":
        authors = s.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        title = _title(s)
        if 1 <= len(authors) <= 3:
            out = f"{head_author(authors[0])} {title} [Электронный ресурс] / {_resp(authors, latin)}"
        elif authors:
            out = f"{title} [Электронный ресурс] / {_resp(authors, latin)}"
        else:
            out = f"{title} [Электронный ресурс]"
        if s.get("site"):
            out += f" // {s['site']}"
        if s.get("year"):
            out += f". – {s['year']}"
        acc = s.get("accessed") or default_accessed
        out += f". – URL: {s['url']}"
        if acc:
            out += f" (дата обращения: {_date(acc)})"
        return _end(out)
    if t == "standard":
        out = f"{s['number']} {str(s['title']).rstrip('.')}"
        imprint = ""
        if s.get("city"):
            imprint = _city(s["city"])
            if s.get("publisher"):
                imprint += f": {s['publisher']}"
            imprint += f", {s['year']}"
        else:
            imprint = str(s["year"])
        out += f". – {imprint}"
        if s.get("pages"):
            out += f". – {s['pages']} с."
        return _end(out)
    if t == "patent":
        authors = s.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        out = f"{s['doc']} {s['number']} {s['country']}. {str(s['title']).rstrip('.')} / {_resp(authors, False)} ({s['country']})"
        tail = []
        if s.get("filed"):
            tail.append(f"Заявл. {s['filed']}")
        if s.get("published"):
            p = f"Опубл. {s['published']}"
            if s.get("bulletin"):
                p += f", Бюл. №{s['bulletin']}"
            tail.append(p)
        if tail:
            out += ". – " + "; ".join(tail)
        return _end(out)
    return _end(str(s.get("title", "")))


def sort_key(s: dict):
    authors = s.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    if s.get("type") == "other":
        base = str(s.get("text", ""))
    elif s.get("type") == "standard":
        base = f"{s.get('number', '')} {s.get('title', '')}"
    elif authors and len(authors) <= 3:
        base = _author(authors[0])[0]
    else:
        base = str(s.get("title", ""))
    base = re.sub(r"^[«\"'„“\[\(]+", "", base.strip()).lower().replace("ё", "е")
    first = base[:1]
    group = 0 if re.match(r"[а-я]", first) else 1 if re.match(r"[a-z]", first) else 2
    return (group, base)


def source_stats(sources: dict, year: int, cited: set):
    """Для бланка аннотации: отечественные/иностранные по давности, интернет-ссылки."""
    st = {"dom": [0, 0, 0], "for": [0, 0, 0], "web": 0, "total": 0}
    for k, s in sources.items():
        if k not in cited:
            continue
        st["total"] += 1
        if s.get("type") == "web":
            st["web"] += 1
        y = s.get("year")
        if not y and s.get("accessed"):
            y = str(s["accessed"])[:4]
        try:
            age = int(year) - int(str(y)[:4])
        except (TypeError, ValueError):
            age = 0
        b = 0 if age <= 5 else 1 if age <= 10 else 2
        st["for" if is_latin(str(s.get("title", s.get("text", "")))) else "dom"][b] += 1
    return st
