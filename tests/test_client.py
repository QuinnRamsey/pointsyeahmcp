"""Tests for PointsYeah HTTP client."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.pointsyeah_client import PointsYeahClient, PointsYeahAPIError
from src.schemas import (
    FlightLocationFilter,
    FlightSearchRequest,
    HotelLocation,
    HotelSearchRequest,
    Pagination,
)


@pytest.mark.asyncio
async def test_missing_api_key_raises_error():
    """Verify that calling client without any API key raises PointsYeahAPIError."""
    client = PointsYeahClient(default_api_key=None)

    req = FlightSearchRequest(
        departure=FlightLocationFilter(airports=["JFK"]),
        arrival=FlightLocationFilter(airports=["LHR"]),
        start_date="2026-07-01",
        end_date="2026-07-15",
    )

    with pytest.raises(PointsYeahAPIError) as exc_info:
        await client.search_flights(req)

    assert "PointsYeah API key is missing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_flight_search_request_formatting():
    """Verify client sends expected headers, method, and payload for flight search."""
    client = PointsYeahClient(default_api_key="default-test-key")

    mock_resp = httpx.Response(
        status_code=200,
        json={"total": 1, "results": [{"program": "UA", "miles": 35000, "tax": 5.6}]},
        request=httpx.Request("POST", "https://ai-api.pointsyeah.com/explorer/search"),
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        req = FlightSearchRequest(
            departure=FlightLocationFilter(airports=["SFO"]),
            arrival=FlightLocationFilter(airports=["HND"]),
            start_date="2026-08-01",
            end_date="2026-08-10",
            cabins=["Business"],
            pagination=Pagination(page=1, page_size=10),
        )

        # Call with per-request API key override
        res = await client.search_flights(req, api_key="custom-user-key")

        assert res["total"] == 1
        assert res["results"][0]["program"] == "UA"

        # Check call arguments
        assert mock_req.call_count == 1
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["url"] == "/explorer/search"
        assert call_kwargs["headers"]["X-API-Key"] == "custom-user-key"
        assert call_kwargs["json"]["departure"]["airports"] == ["SFO"]
        assert call_kwargs["json"]["cabins"] == ["Business"]

    await client.close()


@pytest.mark.asyncio
async def test_upstream_401_error_handling():
    """Verify that upstream 401 returns clear invalid API key message."""
    client = PointsYeahClient(default_api_key="bad-key")

    mock_resp = httpx.Response(
        status_code=401,
        json={"message": "Invalid API Key"},
        request=httpx.Request("GET", "https://ai-api.pointsyeah.com/explorer/count"),
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        with pytest.raises(PointsYeahAPIError) as exc_info:
            await client.get_flight_count()

        assert "invalid, inactive, or unauthorized" in str(exc_info.value)
        assert exc_info.value.status_code == 401

    await client.close()


@pytest.mark.asyncio
async def test_upstream_429_rate_limit_handling():
    """Verify that upstream 429 returns quota message."""
    client = PointsYeahClient(default_api_key="test-key")

    mock_resp = httpx.Response(
        status_code=429,
        json={"message": "Daily limit reached"},
        request=httpx.Request("GET", "https://ai-api.pointsyeah.com/explorer/count"),
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        with pytest.raises(PointsYeahAPIError) as exc_info:
            await client.get_flight_count()

        assert "rate limit reached" in str(exc_info.value)
        assert exc_info.value.status_code == 429

    await client.close()


@pytest.mark.asyncio
async def test_hotel_search_request():
    """Verify hotel search request payload and headers."""
    client = PointsYeahClient(default_api_key="hotel-test-key")

    mock_resp = httpx.Response(
        status_code=200,
        json={"total": 5, "results": [{"name": "Grand Hyatt Tokyo", "points": 25000}]},
        request=httpx.Request("POST", "https://ai-api.pointsyeah.com/hotel/explorer/search"),
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        loc = HotelLocation(
            label="Tokyo, Japan",
            value="Tokyo, Japan",
            latitude=35.6762,
            longitude=139.6503,
            distance=30000,
            dest_type="city",
            country_code="JP",
        )
        req = HotelSearchRequest(location=loc, max_points=30000)

        res = await client.search_hotels(req)
        assert res["total"] == 5
        assert res["results"][0]["name"] == "Grand Hyatt Tokyo"

    await client.close()
