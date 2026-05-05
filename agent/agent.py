import asyncio
import signal

from loguru import logger

from agent.collectors.docker_collector import collect_docker_metrics
from agent.collectors.system import collect_system_metrics
from agent.config import settings
from agent.logs_streamer import LogsStreamer
from agent.sender import MetricsSender


async def _metrics_loop(sender: MetricsSender, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        system_payload = await asyncio.to_thread(collect_system_metrics)
        if await sender.send(system_payload):
            logger.debug("System-метрики отправлены: {}", system_payload)

        docker_payload = await asyncio.to_thread(collect_docker_metrics)
        if await sender.send_docker(docker_payload):
            logger.debug(
                "Docker-метрики отправлены: {} контейнеров",
                len(docker_payload),
            )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.send_interval_seconds)
        except TimeoutError:
            pass


async def run() -> None:
    sender = MetricsSender(
        api_url=settings.api_url,
        api_key=settings.api_key,
        timeout=settings.request_timeout_seconds,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)  # type: ignore[arg-type]

    logger.info(
        "PulseWatch agent запущен: {} (интервал {} c)",
        settings.api_url,
        settings.send_interval_seconds,
    )

    tasks: list[asyncio.Task] = [
        asyncio.create_task(_metrics_loop(sender, stop_event), name="metrics-loop"),
    ]
    if settings.logs_enabled:
        streamer = LogsStreamer(
            ws_base_url=settings.ws_base_url,
            ws_path=settings.logs_ws_path,
            api_key=settings.api_key,
            max_backoff_seconds=settings.logs_reconnect_max_seconds,
        )
        tasks.append(asyncio.create_task(streamer.run(stop_event), name="logs-streamer"))

    try:
        # Ждём либо graceful stop (через stop_event внутри задач), либо падения любой.
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if task.exception() is not None:
                logger.error("Задача {} упала: {}", task.get_name(), task.exception())
    finally:
        stop_event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sender.close()
        logger.info("PulseWatch agent остановлен")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
