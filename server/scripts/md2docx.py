"""轻量 markdown → Word docx(Word COM)。用法: python scripts/md2docx.py <in.md> <out.docx>"""
import sys
from pathlib import Path

import pythoncom
import win32com.client as win32


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    md = src.read_text(encoding="utf-8")
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Add()
        for line in md.splitlines():
            line = line.rstrip()
            if not line.strip():
                continue
            if line.startswith("# "):
                _insert(word, doc, line[2:], "标题 1")
            elif line.startswith("## "):
                _insert(word, doc, line[3:], "标题 2")
            elif line.startswith("### "):
                _insert(word, doc, line[4:], "标题 3")
            elif line.startswith("#### "):
                _insert(word, doc, line[5:], "标题 4")
            elif line.startswith("- ") or line.startswith("* "):
                _insert(word, doc, "• " + line[2:], "列表段落")
            else:
                t = line.replace("**", "").replace("`", "")
                _insert(word, doc, t, "正文")
        doc.SaveAs(str(out.resolve()), FileFormat=16)
        doc.Close(False)
        print("docx 生成:", out.name)
    finally:
        if word:
            word.Quit()
        pythoncom.CoUninitialize()
    return 0


def _insert(word, doc, text: str, style: str) -> None:
    r = doc.Content
    r.InsertAfter(text + "\r")
    r.Style = style


if __name__ == "__main__":
    raise SystemExit(main())
