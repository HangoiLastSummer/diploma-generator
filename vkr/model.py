"""Модель документа: то, во что парсер превращает Markdown, и с чем работают валидатор и билдер."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Src:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


# ---------- inline ----------

@dataclass
class Text:
    s: str


@dataclass
class Emph:            # *курсив* автора
    children: list


@dataclass
class Bold:            # **жирный** — в тексте запрещён (WARN), но рендерится
    children: list


@dataclass
class Code:            # `Identifier` — курсивом, как латиница
    s: str


@dataclass
class Math:            # $x$
    tex: str


@dataclass
class Cite:            # [@key, с. 5; @key2]
    items: list        # [(key, locator|None)]


@dataclass
class Ref:             # @fig:label
    kind: str          # fig|tbl|lst|eq|app
    label: str


@dataclass
class Url:
    s: str


Inline = Union[Text, Emph, Bold, Code, Math, Cite, Ref, Url]


# ---------- blocks ----------

@dataclass
class Heading:
    level: int                 # 1..3 — нумеруемые, 4 — курсивный псевдозаголовок
    inlines: list
    src: Src
    number: str = ""           # заполняет numbering
    kind: str = "chapter"      # chapter | special (введение и т.п.) | appendix
    hid: str = ""              # уникальный id для вёрстки


@dataclass
class Paragraph:
    inlines: list
    src: Src
    pid: str = ""


@dataclass
class ListItem:
    inlines: list
    src: Src
    children: list = field(default_factory=list)   # вложенные ListBlock


@dataclass
class ListBlock:
    style: str                 # dash | dot (1.) | paren (1) -> а), 1))
    items: list
    src: Src
    depth: int = 0


@dataclass
class Figure:
    path: str
    caption: list
    label: str
    src: Src
    width: Optional[float] = None      # доля ширины текста, 0..1
    number: str = ""


@dataclass
class Table:
    caption: list
    label: str
    header: list               # строки шапки: list[list[list[inline]]]; «<» — объединить с левой, «^» — с верхней
    rows: list                 # list[list[list[inline]]]
    src: Src
    align: list = field(default_factory=list)
    numbered_header: bool = False
    number: str = ""


@dataclass
class Listing:
    code: str
    lang: str
    caption: list
    label: str
    src: Src
    number: str = ""


@dataclass
class Formula:
    tex: str
    label: str
    src: Src
    number: str = ""


@dataclass
class Where:                    # пояснение «где …» под формулой
    lines: list                 # list[list[inline]]
    src: Src


Block = Union[Heading, Paragraph, ListBlock, Figure, Table, Listing, Formula, Where]


@dataclass
class Part:
    """Кусок документа из одного или нескольких файлов: введение, основная часть, приложение."""
    role: str                   # intro | body | conclusion | appendix
    blocks: list
    file: str = ""
    title: str = ""             # для приложений
    kind: str = ""              # для приложений: '' | user-guide
    letter: str = ""            # буква приложения
    label: str = ""             # метка @app:...


def walk_inlines(inlines):
    """Обход всех inline-узлов, включая вложенные."""
    for x in inlines:
        yield x
        if isinstance(x, (Emph, Bold)):
            yield from walk_inlines(x.children)


def plain(inlines) -> str:
    out = []
    for x in inlines:
        if isinstance(x, Text):
            out.append(x.s)
        elif isinstance(x, (Emph, Bold)):
            out.append(plain(x.children))
        elif isinstance(x, (Code, Url)):
            out.append(x.s)
        elif isinstance(x, Math):
            out.append(x.tex)
        elif isinstance(x, Ref):
            out.append(f"@{x.kind}:{x.label}")
        elif isinstance(x, Cite):
            out.append("[" + "; ".join("@" + k for k, _ in x.items) + "]")
    return "".join(out)


def block_items(blocks):
    """Все inline-последовательности блока (для валидатора/типографики)."""
    for b in blocks:
        if isinstance(b, (Paragraph, Heading)):
            yield b, b.inlines
        elif isinstance(b, ListBlock):
            yield from _list_inlines(b)
        elif isinstance(b, (Figure, Table, Listing)):
            yield b, b.caption
            if isinstance(b, Table):
                for row in b.header + b.rows:
                    for cell in row:
                        yield b, cell
        elif isinstance(b, Where):
            for ln in b.lines:
                yield b, ln


def _list_inlines(lb):
    for it in lb.items:
        yield it, it.inlines
        for ch in it.children:
            yield from _list_inlines(ch)
