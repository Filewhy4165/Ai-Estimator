from __future__ import annotations

import asyncio
from pathlib import Path

from service.app import _save_uploads


class _UploadStub:
    def __init__(self, *, filename: str, content: bytes, read_chunk: int = 4) -> None:
        self.filename = filename
        self._content = content
        self._read_chunk = max(1, read_chunk)
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._read_chunk
        end = self._offset + size
        chunk = self._content[self._offset : end]
        self._offset = end
        return bytes(chunk)


def test_save_uploads_writes_file_chunks(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    uploads = [
        _UploadStub(filename="drawing one.pdf", content=b"A" * 8, read_chunk=3),
        _UploadStub(filename="drawing_two.pdf", content=b"B" * 7, read_chunk=2),
    ]

    saved_paths = asyncio.run(_save_uploads(uploads, upload_dir))

    assert len(saved_paths) == 2
    assert Path(saved_paths[0]).exists()
    assert Path(saved_paths[0]).read_bytes() == b"A" * 8
    assert Path(saved_paths[1]).exists()
    assert Path(saved_paths[1]).read_bytes() == b"B" * 7
    assert Path(saved_paths[0]).name.startswith("001_drawing_one")
    assert Path(saved_paths[1]).name.startswith("002_drawing_two")
