"""多格式文档解析:txt / docx / doc / pdf → 纯文本。

- txt:UTF-8 优先,GBK 兜底;
- docx:zipfile 解 word/document.xml,段落/表格行保留换行;
- doc:优先 antiword,其次 LibreOffice headless 转换;均不可用时给出明确建议;
- pdf:pypdf 抽取文本层;扫描件(无文本层)提示先转文字版。
"""
from __future__ import annotations

import html
import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

SUPPORTED = (".txt", ".docx", ".doc", ".pdf")


def parse_upload(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return _parse_txt(data)
    if ext == ".docx":
        return _parse_docx(data)
    if ext == ".doc":
        return _parse_doc(data, filename)
    if ext == ".pdf":
        return _parse_pdf(data)
    raise ValueError(f"不支持的格式「{ext or '无扩展名'}」,目前支持 .txt / .docx / .doc / .pdf")


def _parse_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")


def _parse_docx(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        xml = z.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError(f"docx 文件损坏或格式不正确: {e}") from e
    xml = re.sub(r"<w:tab\s*/?>", "\t", xml)
    xml = re.sub(r"<w:br\s*/?>", "\n", xml)
    xml = re.sub(r"</w:tc>", "\t", xml)          # 表格单元格
    xml = re.sub(r"</w:p>", "\n", xml)           # 段落
    xml = re.sub(r"<w:p\b[^>]*>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text.strip():
        raise ValueError("docx 未解析出任何文本,请确认文件内容")
    return text.strip()


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("服务端缺少 pypdf 依赖,无法解析 PDF") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"PDF 解析失败: {e}") from e
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise ValueError("该 PDF 没有可抽取的文本层(可能是扫描件/图片),请先转成文字版再上传")
    return text


def _parse_doc(data: bytes, filename: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / (Path(filename).stem + ".doc")
        src.write_bytes(data)
        # 1) antiword
        try:
            out = subprocess.run(["antiword", str(src)], capture_output=True, timeout=60)
            if out.returncode == 0:
                text = out.stdout.decode("utf-8", errors="replace").strip()
                if text:
                    return text
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # 2) LibreOffice headless → txt
        try:
            subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text",
                            "--outdir", td, str(src)],
                           capture_output=True, timeout=180)
            txt = Path(td) / (src.stem + ".txt")
            if txt.exists():
                text = txt.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return text
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    raise ValueError(".doc(旧版二进制)解析不可用:服务器未安装 antiword/LibreOffice,"
                     "建议另存为 .docx 或导出 PDF 后重新上传")
