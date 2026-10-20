"""Write index.html: template.html with data.json in place of __DATA__ (the prototype's build step).

    .venv/bin/python ui/web/tools/build_index.py
"""

from pathlib import Path

WEB = Path(__file__).resolve().parent.parent

template = (WEB / "template.html").read_text(encoding="utf-8")
data = (WEB / "data.json").read_text(encoding="utf-8").strip()
assert template.count("__DATA__") == 1
(WEB / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
print("wrote index.html")
