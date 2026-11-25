"""python -m pytest tests  (сборка примера без вёрстки и ключевые правила валидатора)"""
import shutil
from pathlib import Path

from vkr.bib import format_source
from vkr.issues import Issues
from vkr.parser import parse_markdown
from vkr.pipeline import build, prepare

ROOT = Path(__file__).resolve().parents[1]


def test_example_has_no_errors():
    pr, nb, issues = prepare(ROOT / "example" / "diploma.yaml")
    assert not issues.errors, [str(i) for i in issues.errors]


def test_example_builds(tmp_path):
    out = tmp_path / "x.docx"
    pr, issues, _ = build(ROOT / "example" / "diploma.yaml", out, layout=False)
    assert out.exists()


def test_section_must_end_with_text(tmp_path):
    shutil.copytree(ROOT / "example", tmp_path / "p")
    f = tmp_path / "p" / "chapters" / "1-analysis.md"
    t = f.read_text(encoding="utf-8").replace(
        "Рабочее место пользователя должно соответствовать требованиям санитарных норм [@sanpin].\n",
        "Рабочее место по нормам [@sanpin] на рисунке @fig:x.\n\n![Схема](img/arch.png){#fig:x}\n")
    f.write_text(t, encoding="utf-8")
    pr, nb, issues = prepare(tmp_path / "p" / "diploma.yaml")
    assert any(i.rule == "E8" for i in issues.errors)


def test_gost_book():
    s = format_source({"type": "book", "authors": ["Шляндин В.М."], "title": "Цифровые измерительные устройства",
                       "kind": "учебное пособие", "city": "Москва", "publisher": "Высшая школа", "year": 2005,
                       "pages": 335})
    assert s == "Шляндин, В.М. Цифровые измерительные устройства: учебное пособие / В.М. Шляндин. – М.: Высшая школа, 2005. – 335 с."


def test_parser_strips_manual_numbers():
    iss = Issues()
    bl = parse_markdown("## 1.2. Заголовок.\n", "t.md", iss)
    assert bl[0].inlines[0].s == "Заголовок"
