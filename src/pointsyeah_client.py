"""Asynchronous HTTP client for the PointsYeah Public API.

Includes retry logic, per-request credentials, connection pooling,
and structured error reporting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx

from src.config import config
from src.schemas import (
    FlightAggregateRequest,
    FlightFilterRangeRequest,
    FlightRecommendRequest,
    FlightSearchRequest,
    HotelCalendarRequest,
    HotelDetailRequest,
    HotelMapRequest,
    HotelRecommendRequest,
    HotelSearchRequest,
)

logger = logging.getLogger("pointsyeah-client")


class PointsYeahAPIError(Exception):
    """Exception raised when an upstream PointsYeah API call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class PointsYeahClient:
    """Async client communicating with PointsYeah REST endpoints."""

    def __init__(self, base_url: Optional[str] = None, default_api_key: Optional[str] = None):
        self.base_url = (base_url or config.POINTSYEAH_BASE_URL).rstrip("/")
        self.default_api_key = default_api_key or config.DEFAULT_POINTSYEAH_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or initialize reusable httpx AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "PointsYeah-MCP-Middleware/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _resolve_api_key(self, per_request_key: Optional[str] = None) -> str:
        """Resolve API key from per-request argument or default server env."""
        key = per_request_key or self.default_api_key
        if not key or not key.strip():
            raise PointsYeahAPIError(
                "PointsYeah API key is missing. Please provide 'pointsyeah_api_key' in the tool call "
                "or configure DEFAULT_POINTSYEAH_API_KEY on the server."
            )
        return key.strip()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        api_key: Optional[str] = None,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Perform HTTP request with error handling and retry mechanism."""
        resolved_key = self._resolve_api_key(api_key)
        client = await self.get_http_client()

        headers = {
            "X-API-Key": resolved_key,
        }

        attempt = 0
        backoff = 0.5

        while True:
            attempt += 1
            try:
                response = await client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    json=json_data,
                    params=params,
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except Exception as err:
                        raise PointsYeahAPIError(
                            f"Failed to parse JSON response from PointsYeah: {err}",
                            status_code=200,
                            details=response.text,
                        )

                # Handle HTTP errors
                error_body: Any = None
                try:
                    error_body = response.json()
                except Exception:
                    error_body = response.text

                # Specific status code messages
                if response.status_code in (401, 403):
                    raise PointsYeahAPIError(
                        "PointsYeah API key is invalid, inactive, or unauthorized.",
                        status_code=response.status_code,
                        details=error_body,
                    )
                elif response.status_code == 429:
                    raise PointsYeahAPIError(
                        "PointsYeah rate limit reached (e.g. 1000 calls/day limit).",
                        status_code=429,
                        details=error_body,
                    )
                elif response.status_code >= 500 and attempt <= max_retries:
                    logger.warning(
                        f"PointsYeah returned {response.status_code}, retrying attempt {attempt}/{max_retries}..."
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                else:
                    msg = f"PointsYeah API error ({response.status_code}): {error_body}"
                    raise PointsYeahAPIError(
                        msg, status_code=response.status_code, details=error_body
                    )

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt <= max_retries:
                    logger.warning(
                        f"Network error communicating with PointsYeah ({exc}), retrying attempt {attempt}/{max_retries}..."
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise PointsYeahAPIError(
                    f"Network error contacting PointsYeah API: {exc}", details=str(exc)
                )

    # -------------------------------------------------------------------------
    # Flight API Methods
    # -------------------------------------------------------------------------

    async def search_flights(
        self, request: FlightSearchRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for award flight availability."""
        payload = request.model_dump(exclude_none=True)
        return await self._request("POST", "/explorer/search", api_key=api_key, json_data=payload)

    async def get_flight_aggregates(
        self, request: FlightAggregateRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregated flight search results for map visualization."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/explorer/search/aggregate", api_key=api_key, json_data=payload
        )

    async def get_flight_count(self, api_key: Optional[str] = None) -> Dict[str, Any]:
        """Get total count of award flights available in PointsYeah explorer."""
        return await self._request("GET", "/explorer/count", api_key=api_key)

    async def get_flight_filter_ranges(
        self, request: FlightFilterRangeRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get min/max ranges for points, tax, duration in a given route."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/explorer/get_filter_range", api_key=api_key, json_data=payload
        )

    async def get_flight_recommendations(
        self, request: FlightRecommendRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get recommended flight routes based on departure."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/explorer/recommend", api_key=api_key, json_data=payload
        )

    # -------------------------------------------------------------------------
    # Hotel API Methods
    # -------------------------------------------------------------------------

    async def search_hotels(
        self, request: HotelSearchRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for hotel award availability."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/hotel/explorer/search", api_key=api_key, json_data=payload
        )

    async def get_hotel_details(
        self, request: HotelDetailRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get details for a specific hotel property."""
        payload = request.model_dump(exclude_none=True)
        return await self._request("POST", "/hotel/detail", api_key=api_key, json_data=payload)

    async def get_hotel_calendar(
        self, request: HotelCalendarRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get daily availability calendar for a specific hotel property."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/hotel/explorer/calendar/v2", api_key=api_key, json_data=payload
        )

    async def get_hotel_map(
        self, request: HotelMapRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get hotel counts grouped by country for map visualization."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/hotel/explorer/map", api_key=api_key, json_data=payload
        )

    async def get_hotel_recommendations(
        self, request: HotelRecommendRequest, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get recommended hotels based on location."""
        payload = request.model_dump(exclude_none=True)
        return await self._request(
            "POST", "/hotel/explorer/recommend", api_key=api_key, json_data=payload
        )


# Global singleton client
pointsyeah_client = PointsYeahClient()
