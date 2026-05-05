"""Утилита для стриминга CSV-ответов FastAPI."""

import csv
import io
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse


def stream_csv(
    filename: str,
    header: list[str],
    rows: AsyncIterator[dict],
) -> StreamingResponse:
    """
    Стримит CSV-ответ. rows — async-генератор словарей с ключами из header.
    """

    async def generate() -> AsyncIterator[str]:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header)
        writer.writeheader()
        yield buf.getvalue()

        async for row in rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=header)
            writer.writerow(row)
            yield buf.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
