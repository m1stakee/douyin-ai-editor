"""Consistent Unicode text I/O for Windows-created workflow files."""
from pathlib import Path
import local_logger


TEXT_READ_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


def read_text(path: str | Path) -> str:
    target = Path(path)
    local_logger.info("file.read path=%s", target)
    last_error: UnicodeDecodeError | None = None
    for encoding in TEXT_READ_ENCODINGS:
        try:
            return target.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error or UnicodeDecodeError("utf-8", b"", 0, 1, "无法读取文本")


def write_text(path: str | Path, value: str, *, bom: bool = False) -> Path:
    target = Path(path)
    try:
        local_logger.info("file.write.start path=%s chars=%s", target, len(str(value)))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(value), encoding="utf-8-sig" if bom else "utf-8", newline="\n")
        local_logger.info("file.write.ok path=%s", target)
    except Exception:
        local_logger.error("file.write.failed path=%s", target, exc_info=True)
        raise
    return target
