import asyncio
import signal

from loguru import logger

from agent.collectors.docker_collector import collect_docker_metrics
from agent.collectors.system import collect_system_metrics
from agent.config import settings
from agent.sender import MetricsSender


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

    try:
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
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.send_interval_seconds
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await sender.close()
        logger.info("PulseWatch agent остановлен")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
