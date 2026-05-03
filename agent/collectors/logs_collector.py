import asyncio
from collections.abc import AsyncIterator

from loguru import logger


async def stream_journal_logs() -> AsyncIterator[str]:
    """Стримит journald построчно в JSON.

    `-n 0` — без истории, только новые записи.
    `-f`  — follow.
    """
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "-f",
        "-o",
        "json",
        "-n",
        "0",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                # journalctl завершился сам (редко) — выходим из цикла
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n")
    finally:
        # Без terminate в finally — zombie journalctl до конца жизни процесса.
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("journalctl не остановился по SIGTERM, шлю SIGKILL")
                proc.kill()
                await proc.wait()
