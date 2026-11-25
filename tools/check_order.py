"""Проверка порядка дочерних элементов pPr/rPr/tblPr/settings в docx (Word строг к нему)."""
import sys, zipfile
from lxml import etree
sys.path.insert(0, ".")
from vkr.builder import PPR_ORDER, RPR_ORDER, TBLPR_ORDER, SETTINGS_ORDER
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
bad = 0
z = zipfile.ZipFile(sys.argv[1])
for name in [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]:
    root = etree.fromstring(z.read(name))
    for tag, order in (("pPr", PPR_ORDER), ("rPr", RPR_ORDER), ("tblPr", TBLPR_ORDER), ("settings", SETTINGS_ORDER)):
        for el in root.iter(W + tag):
            names = [c.tag.split("}")[1] for c in el if c.tag.startswith(W)]
            idx = [order.index(n) for n in names if n in order]
            if idx != sorted(idx):
                bad += 1
                if bad < 6:
                    print(name, tag, names)
print("нарушений порядка:", bad)
