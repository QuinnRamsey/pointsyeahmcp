"""Tests for flight and hotel MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.server import mcp_server
from src.pointsyeah_client import pointsyeah_client


@pytest.mark.asyncio
async def test_search_flights_tool_validation():
    """Verify tool returns validation error when missing departure or arrival."""
    tools = {t.name: t for t in mcp_server._tool_manager.list_tools()}
    assert "search_flights" in tools

    # Call tool with no locations
    res = await mcp_server.call_tool(
        "search_flights",
        {
            "start_date": "2026-07-01",
            "end_date": "2026-07-10",
        },
    )
    assert len(res.content) > 0
    assert "At least one departure location" in res.content[0].text


@pytest.mark.asyncio
async def test_search_flights_tool_success():
    """Verify search_flights calls client and formats results."""
    mock_data = {
        "total": 2,
        "results": [
            {"program": "DL", "miles": 45000, "tax": 11.2, "cabin": "Economy"},
            {"program": "AF", "miles": 50000, "tax": 140.0, "cabin": "Business"},
        ],
    }

    with patch.object(pointsyeah_client, "search_flights", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_data

        res = await mcp_server.call_tool(
            "search_flights",
            {
                "departure_airports": ["JFK"],
                "arrival_airports": ["CDG"],
                "start_date": "2026-07-01",
                "end_date": "2026-07-15",
                "cabins": ["Economy", "Business"],
                "pointsyeah_api_key": "user-custom-api-key",
            },
        )

        assert len(res.content) > 0
        content = json.loads(res.content[0].text)
        assert content["total"] == 2
        assert content["results"][0]["program"] == "DL"

        # Check that per-request key was passed
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["api_key"] == "user-custom-api-key"


@pytest.mark.asyncio
async def test_search_hotels_preset_city():
    """Verify search_hotels automatically resolves known cities like 'London'."""
    mock_data = {
        "total": 1,
        "results": [{"name": "The London EDITION", "points": 85000}],
    }

    with patch.object(pointsyeah_client, "search_hotels", new_callable=AsyncMock) as mock_hotel:
        mock_hotel.return_value = mock_data

        res = await mcp_server.call_tool(
            "search_hotels",
            {
                "location_name": "London",
                "start_date": "2026-08-01",
                "end_date": "2026-08-05",
            },
        )

        assert len(res.content) > 0
        content = json.loads(res.content[0].text)
        assert content["total"] == 1
        assert content["results"][0]["name"] == "The London EDITION"

        # Verify coordinates were auto-resolved
        called_req = mock_hotel.call_args.args[0]
        assert called_req.location.country_code == "GB"
        assert abs(called_req.location.latitude - 51.5074) < 0.01


@pytest.mark.asyncio
async def test_get_hotel_calendar_tool():
    """Verify hotel calendar tool call."""
    mock_cal = {
        "code": 0,
        "success": True,
        "data": {
            "hotel": {"name": "Residence Inn Clayton", "program": "marriott"},
            "months": [{"month": "2026-07", "points": [32000, 32000]}],
        },
    }

    with patch.object(pointsyeah_client, "get_hotel_calendar", new_callable=AsyncMock) as mock_c:
        mock_c.return_value = mock_cal

        res = await mcp_server.call_tool(
            "get_hotel_calendar",
            {
                "property_id": 12345,
                "month": "2026-07",
            },
        )

        assert len(res.content) > 0
        content = json.loads(res.content[0].text)
        assert content["data"]["hotel"]["name"] == "Residence Inn Clayton"
