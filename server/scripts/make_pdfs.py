"""将 doc/ 下三份课程素材 docx 转为 PDF(A级测试单要求「3份PDF」RAG 链路演示)。

首选 Word COM(pywin32,保真、零新增依赖);不可用时回退 fpdf2+simhei.ttf 文本重排。
输出:doc/pdf/<原文件名>.pdf

红线:生成的 PDF 仅用于 SaaS 演示租户上传,严禁种入官方 kb-c
(否则「边界1-平台会员价格」用例被破坏)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "doc"
OUT_DIR = DOC_DIR / "pdf"

SOURCES = [
    "学生个人课程资料.docx",
    "教师个人培训资料.docx",
    "平台与企业服务资料.docx",
]

WD_FORMAT_PDF = 17


def via_word_com(src: Path, dst: Path) -> bool:
    """Word COM 另存为 PDF(保真)。"""
    try:
        import pythoncom
        import win32com.client as win32
    except ImportError:
        return False
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), ReadOnly=True)
        doc.SaveAs(str(dst), FileFormat=WD_FORMAT_PDF)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  Word COM 失败: {e}", file=sys.stderr)
        return False
    finally:
        try:
            if doc:
                doc.Close(False)
            if word:
                word.Quit()
        except Exception:  # noqa: BLE001
            pass
        pythoncom.CoUninitialize()


def _docx_paragraphs(src: Path) -> list[str]:
    """docx 段落+表格文本提取(与 app/core/ingest/parse.py 同款轻量解析)。"""
    import re
    import zipfile

    xml = zipfile.ZipFile(src).read("word/document.xml").decode("utf-8")
    paras = re.split(r"</w:p>", xml)
    out = []
    for p in paras:
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)
        line = "".join(texts).strip()
        if line:
            out.append(line)
    return out


def via_fpdf(src: Path, dst: Path) -> bool:
    """fpdf2 + simhei.ttf 文本重排(回退路径)。"""
    try:
        from fpdf import FPDF
    except ImportError:
        print("  fpdf2 未安装(回退路径不可用): pip install fpdf2", file=sys.stderr)
        return False
    font = Path("C:/Windows/Fonts/simhei.ttf")
    if not font.exists():
        print(f"  中文字体不存在: {font}", file=sys.stderr)
        return False

    class PDF(FPDF):
        def footer(self):
            self.set_y(-15)
            self.set_font("simhei", "", 8)
            self.cell(0, 10, f"{self.page_no()}", align="C")

    pdf = PDF()
    pdf.add_font("simhei", "", str(font))
    pdf.set_font("simhei", "", 11)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    for line in _docx_paragraphs(src):
        pdf.multi_cell(0, 6, line)
    pdf.output(str(dst))
    return True


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    ok = 0
    for name in SOURCES:
        src = DOC_DIR / name
        if not src.exists():
            print(f"缺少素材: {src}", file=sys.stderr)
            continue
        dst = OUT_DIR / (src.stem + ".pdf")
        print(f"转换 {name} ->", dst.name)
        if via_word_com(src, dst) or via_fpdf(src, dst):
            size = dst.stat().st_size
            print(f"  完成 ({size/1024:.0f} KB)")
            ok += 1
        else:
            print(f"  失败: {name}", file=sys.stderr)
    print(f"完成 {ok}/{len(SOURCES)}")
    return 0 if ok == len(SOURCES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
