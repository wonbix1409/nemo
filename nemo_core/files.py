"""Чтение текста из файлов: .txt, .md, .csv, .docx."""
from __future__ import annotations

from pathlib import Path


def read_text_file(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        try:
            import docx  # python-docx
        except ImportError as e:
            raise RuntimeError("Для .docx нужен пакет python-docx") from e
        d = docx.Document(str(p))
        lines = [para.text for para in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                lines.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(lines)
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return p.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")
