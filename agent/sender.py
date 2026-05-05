import httpx
from loguru import logger


class MetricsSender:
    def __init__(self, api_url: str, api_key: str, timeout: float = 5.0) -> None:
        self._base_url = api_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._client = httpx.AsyncClient(timeout=timeout)

    async def _post(self, path: str, payload) -> bool:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.post(url, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            logger.warning("Сетевая ошибка при POST {}: {}", path, exc)
            return False

        if response.status_code == 201:
            return True

        logger.warning(
            "Сервер вернул {} на POST {}: {}",
            response.status_code,
            path,
            response.text,
        )
        return False

    async def send(self, payload: dict) -> bool:
        return await self._post("/metrics", payload)

    async def send_docker(self, payload: list[dict]) -> bool:
        return await self._post("/docker-metrics", payload)

    async def close(self) -> None:
        await self._client.aclose()
