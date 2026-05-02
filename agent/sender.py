import httpx
from loguru import logger


class MetricsSender:
    def __init__(self, api_url: str, api_key: str, timeout: float = 5.0) -> None:
        self._endpoint = f"{api_url.rstrip('/')}/metrics"
        self._headers = {"X-API-Key": api_key}
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send(self, payload: dict) -> bool:
        try:
            response = await self._client.post(
                self._endpoint, json=payload, headers=self._headers
            )
        except httpx.HTTPError as exc:
            logger.warning("Сетевая ошибка при отправке метрик: {}", exc)
            return False

        if response.status_code == 201:
            return True

        logger.warning(
            "Сервер вернул {} при отправке метрик: {}",
            response.status_code,
            response.text,
        )
        return False

    async def close(self) -> None:
        await self._client.aclose()
