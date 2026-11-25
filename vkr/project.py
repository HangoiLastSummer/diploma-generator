"""Загрузка проекта: diploma.yaml + профиль кафедры + Markdown-файлы + sources.yaml."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .issues import Issues
from .model import Part, Src
from .parser import parse_markdown

PROFILES = Path(__file__).parent / "profiles"
APPENDIX_LETTERS = "АБВГДЖКЛМНПРСТУФХЦШЭЮЯ"

DEGREES = {
    r"к\.?\s*т\.?\s*н\.?": "канд. техн. наук",
    r"к\.?\s*п\.?\s*н\.?": "канд. пед. наук",
    r"к\.?\s*ф\.?-?\s*м\.?\s*н\.?": "канд. физ.-мат. наук",
    r"к\.?\s*э\.?\s*н\.?": "канд. экон. наук",
    r"д\.?\s*т\.?\s*н\.?": "д-р техн. наук",
    r"д\.?\s*п\.?\s*н\.?": "д-р пед. наук",
    r"д\.?\s*ф\.?-?\s*м\.?\s*н\.?": "д-р физ.-мат. наук",
    r"д\.?\s*э\.?\s*н\.?": "д-р экон. наук",
}


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class LineIndex:
    """Номер строки YAML для пути ключей (для сообщений об ошибках)."""

    def __init__(self, text: str):
        try:
            self.root = yaml.compose(text)
        except yaml.YAMLError:
            self.root = None

    def line(self, *path) -> int:
        node = self.root
        last = 1
        for key in path:
            if node is None:
                break
            if isinstance(node, yaml.MappingNode):
                for k, v in node.value:
                    if k.value == key:
                        last = k.start_mark.line + 1
                        node = v
                        break
                else:
                    return last
            elif isinstance(node, yaml.SequenceNode) and isinstance(key, int) and key < len(node.value):
                node = node.value[key]
                last = node.start_mark.line + 1
            else:
                break
        return last


@dataclass
class Project:
    root: Path
    cfg: dict
    issues: Issues
    intro: Part | None = None
    body: Part | None = None
    conclusion: Part | None = None
    appendices: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    sources_lines: LineIndex | None = None
    cfg_lines: LineIndex | None = None
    md_texts: dict = field(default_factory=dict)

    def path(self, rel: str) -> Path:
        return (self.root / rel).resolve()


def normalize_degree(s: str, issues: Issues, src: Src) -> str:
    if not s:
        return s
    for pat, full in DEGREES.items():
        if re.fullmatch(pat, s.strip(), flags=re.I):
            if s.strip() != full:
                issues.fixed("K2", f"учёная степень «{s}» → «{full}»", src)
            return full
    return s.strip()


def load_project(config_path: str | Path, parse_md: bool = True) -> Project:
    config_path = Path(config_path).resolve()
    root = config_path.parent
    issues = Issues()
    text = config_path.read_text(encoding="utf-8")
    li = LineIndex(text)
    try:
        user = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        issues.err("CFG", f"diploma.yaml не разобран: {e}", Src(config_path.name, 1))
        return Project(root, {}, issues)
    prof_name = user.get("profile", "pgu-povt")
    prof_path = PROFILES / f"{prof_name}.yaml"
    if not prof_path.exists():
        issues.err("CFG", f"нет профиля «{prof_name}»", Src(config_path.name, li.line("profile")))
        prof = {}
    else:
        prof = yaml.safe_load(prof_path.read_text(encoding="utf-8"))
    cfg = deep_merge(prof, user)
    cfg["_config_file"] = config_path.name
    pr = Project(root, cfg, issues, cfg_lines=li)
    _check_cfg(pr)
    if parse_md:
        _load_parts(pr)
        _load_sources(pr)
    return pr


def _src(pr, *path):
    return Src(pr.cfg.get("_config_file", "diploma.yaml"), pr.cfg_lines.line(*path) if pr.cfg_lines else 1)


def _check_cfg(pr: Project):
    c = pr.cfg
    req = [("year",), ("topic",), ("student", "name"), ("student", "group"), ("supervisor", "name"),
           ("supervisor", "degree"), ("supervisor", "title"), ("annotation", "ru"), ("annotation", "en"),
           ("content", "intro"), ("content", "chapters"), ("content", "conclusion")]
    for path in req:
        v = c
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if v in (None, "", []):
            pr.issues.err("CFG", f"не заполнено поле {'.'.join(path)}", _src(pr, *path[:-1]) if len(path) > 1 else _src(pr))
    for who in ("supervisor", "head"):
        if isinstance(c.get(who), dict) and c[who].get("degree"):
            c[who]["degree"] = normalize_degree(c[who]["degree"], pr.issues, _src(pr, who, "degree"))
    if isinstance(c.get("task_head"), dict) and c["task_head"].get("degree"):
        c["task_head"]["degree"] = normalize_degree(c["task_head"]["degree"], pr.issues, _src(pr, "task_head", "degree"))
    # тема: одинаковая на титуле и в задании — она одна, но двойные пробелы чистим
    if isinstance(c.get("topic"), str):
        t = re.sub(r"[ \t]+", " ", c["topic"].strip())
        if t != c["topic"]:
            pr.issues.fixed("K4", "в теме убраны лишние пробелы", _src(pr, "topic"))
        c["topic"] = t.strip("«»\" ")
    for k in ("deadline",):
        if k in c and not isinstance(c[k], (dt.date, str)):
            pr.issues.err("CFG", f"{k}: ожидается дата ГГГГ-ММ-ДД", _src(pr, k))


def _read_md(pr: Project, rel: str, src: Src) -> list:
    p = pr.path(rel)
    if not p.exists():
        pr.issues.err("CFG", f"файл не найден: {rel}", src)
        return []
    text = p.read_text(encoding="utf-8")
    relname = str(Path(rel))
    pr.md_texts[relname] = text
    return parse_markdown(text, relname, pr.issues)


def _load_parts(pr: Project):
    c = pr.cfg.get("content") or {}
    if c.get("intro"):
        pr.intro = Part("intro", _read_md(pr, c["intro"], _src(pr, "content", "intro")), c["intro"])
    blocks = []
    for k, f in enumerate(c.get("chapters") or []):
        blocks += _read_md(pr, f, _src(pr, "content", "chapters", k))
    pr.body = Part("body", blocks)
    if c.get("conclusion"):
        pr.conclusion = Part("conclusion", _read_md(pr, c["conclusion"], _src(pr, "content", "conclusion")),
                             c["conclusion"])
    for k, a in enumerate(c.get("appendices") or []):
        if isinstance(a, str):
            a = {"file": a}
        src = _src(pr, "content", "appendices", k)
        kind = a.get("kind", "")
        title = a.get("title") or ("Руководство пользователя" if kind == "user-guide" else "")
        if not title:
            pr.issues.err("CFG", f"у приложения {a.get('file')} нет title", src)
        letter = APPENDIX_LETTERS[k] if k < len(APPENDIX_LETTERS) else str(k - len(APPENDIX_LETTERS) + 1)
        label = a.get("label") or Path(a.get("file", f"app{k}")).stem
        pr.appendices.append(Part("appendix", _read_md(pr, a["file"], src) if a.get("file") else [],
                                  a.get("file", ""), title, kind, letter, label))


SOURCE_REQUIRED = {
    "book": ["authors", "title", "city", "publisher", "year"],
    "article": ["authors", "title", "journal", "year"],
    "web": ["title", "url"],
    "standard": ["number", "title", "year"],
    "patent": ["doc", "number", "country", "title", "authors"],
    "thesis": ["authors", "title", "city", "year"],
    "other": ["text"],
}


def _load_sources(pr: Project):
    rel = (pr.cfg.get("content") or {}).get("sources", "sources.yaml")
    p = pr.path(rel)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    pr.sources_lines = LineIndex(text)
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        pr.issues.err("I4", f"{rel} не разобран: {e}", Src(rel, 1))
        return
    for key, s in data.items():
        src = Src(rel, pr.sources_lines.line(key))
        if not isinstance(s, dict):
            pr.issues.err("I4", f"источник {key}: ожидается набор полей", src)
            continue
        t = s.get("type", "book")
        if t not in SOURCE_REQUIRED:
            pr.issues.err("I4", f"источник {key}: неизвестный type «{t}»", src,
                          "допустимо: " + ", ".join(SOURCE_REQUIRED))
            continue
        miss = [f for f in SOURCE_REQUIRED[t] if not s.get(f)]
        if miss:
            pr.issues.err("I4", f"источник {key} ({t}): не заполнено {', '.join(miss)}", src)
        s["_src"] = src
        s["_key"] = key
        pr.sources[str(key)] = s
