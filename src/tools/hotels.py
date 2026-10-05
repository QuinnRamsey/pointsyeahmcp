"""Hotel award search, details, and calendar tools for PointsYeah MCP server."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import Context, MCPServer

from src.pointsyeah_client import pointsyeah_client, PointsYeahAPIError
from src.schemas import (
    HotelCalendarRequest,
    HotelDetailRequest,
    HotelLocation,
    HotelMapRequest,
    HotelRecommendRequest,
    HotelSearchRequest,
    Pagination,
)

# Reference coordinates for common global travel hubs to make tool calls effortless for LLMs
COMMON_CITY_COORDINATES: Dict[str, Dict[str, Any]] = {
    "new york": {"label": "New York, NY", "value": "New York, NY", "lat": 40.7128, "lon": -74.0060, "country": "US"},
    "nyc": {"label": "New York, NY", "value": "New York, NY", "lat": 40.7128, "lon": -74.0060, "country": "US"},
    "los angeles": {"label": "Los Angeles, CA", "value": "Los Angeles, CA", "lat": 34.0522, "lon": -118.2437, "country": "US"},
    "lax": {"label": "Los Angeles, CA", "value": "Los Angeles, CA", "lat": 34.0522, "lon": -118.2437, "country": "US"},
    "chicago": {"label": "Chicago, IL", "value": "Chicago, IL", "lat": 41.8781, "lon": -87.6298, "country": "US"},
    "san francisco": {"label": "San Francisco, CA", "value": "San Francisco, CA", "lat": 37.7749, "lon": -122.4194, "country": "US"},
    "miami": {"label": "Miami, FL", "value": "Miami, FL", "lat": 25.7617, "lon": -80.1918, "country": "US"},
    "london": {"label": "London, UK", "value": "London, UK", "lat": 51.5074, "lon": -0.1278, "country": "GB"},
    "paris": {"label": "Paris, France", "value": "Paris, France", "lat": 48.8566, "lon": 2.3522, "country": "FR"},
    "tokyo": {"label": "Tokyo, Japan", "value": "Tokyo, Japan", "lat": 35.6762, "lon": 139.6503, "country": "JP"},
    "honolulu": {"label": "Honolulu, HI", "value": "Honolulu, HI", "lat": 21.3069, "lon": -157.8583, "country": "US"},
    "las vegas": {"label": "Las Vegas, NV", "value": "Las Vegas, NV", "lat": 36.1699, "lon": -115.1398, "country": "US"},
}


def _extract_api_key(tool_key: Optional[str], ctx: Optional[Context]) -> Optional[str]:
    """Extract PointsYeah API key from tool argument, client HTTP headers, or composite OAuth token."""
    if tool_key and tool_key.strip():
        return tool_key.strip()
    if ctx is not None:
        try:
            headers = ctx.headers
            if headers:
                for header, val in headers.items():
                    if header.lower() in ("x-pointsyeah-api-key", "pointsyeah-api-key"):
                        return val.strip()

                # Also extract from composite Authorization: Bearer <server_key>:<pointsyeah_key>
                auth = headers.get("authorization") or headers.get("Authorization")
                if auth and auth.startswith("Bearer "):
                    token = auth[7:].strip()
                    if ":" in token:
                        parts = token.split(":", 1)
                        py_candidate = parts[1].strip()
                        if py_candidate and py_candidate.lower() not in (
                            "pointsyeah",
                            "gemini",
                            "client",
                            "default",
                            "none",
                        ):
                            return py_candidate
        except (ValueError, AttributeError):
            pass
    return None


def _build_hotel_location(
    city_or_label: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    country_code: Optional[str] = None,
    radius_meters: int = 30000,
) -> HotelLocation:
    """Resolve location into HotelLocation model using lookup or provided lat/lon."""
    normalized = city_or_label.strip().lower()

    if latitude is not None and longitude is not None:
        return HotelLocation(
            label=city_or_label,
            value=city_or_label,
            latitude=latitude,
            longitude=longitude,
            distance=radius_meters,
            dest_type="city",
            country_code=(country_code or "US").upper(),
        )

    # Check preset cities
    if normalized in COMMON_CITY_COORDINATES:
        info = COMMON_CITY_COORDINATES[normalized]
        return HotelLocation(
            label=info["label"],
            value=info["value"],
            latitude=info["lat"],
            longitude=info["lon"],
            distance=radius_meters,
            dest_type="city",
            country_code=info["country"],
        )

    # Default to 0.0 with warning if no coordinates provided
    return HotelLocation(
        label=city_or_label,
        value=city_or_label,
        latitude=latitude or 0.0,
        longitude=longitude or 0.0,
        distance=radius_meters,
        dest_type="city",
        country_code=(country_code or "US").upper(),
    )


def register_hotel_tools(server: MCPServer) -> None:
    """Register all hotel-related tools onto the MCPServer."""

    @server.tool()
    async def search_hotels(
        location_name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        country_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_points: int = 200000,
        max_prices: int = 5000,
        programs: Optional[List[str]] = None,
        amenities: Optional[List[str]] = None,
        weekend_only: bool = False,
        sort: str = "points",
        page: int = 1,
        page_size: int = 10,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Search for hotel award availability across major loyalty programs (Hyatt, Marriott, IHG, Hilton, etc.).

        Returns hotel properties with redemption points pricing, cash pricing, and transfer partner information.

        Args:
            location_name: City or destination name (e.g. 'New York, NY', 'Tokyo', 'London').
            latitude: Optional latitude. If omitted, common cities will be resolved automatically.
            longitude: Optional longitude. If omitted, common cities will be resolved automatically.
            country_code: Two-letter ISO country code (e.g. 'US', 'GB', 'JP').
            start_date: Check-in date (YYYY-MM-DD).
            end_date: Check-out date (YYYY-MM-DD).
            max_points: Maximum points per night (default 200,000).
            max_prices: Maximum cash price in USD (default $5,000).
            programs: Hotel loyalty programs to filter by, e.g. ['hyatt', 'marriott', 'ihg', 'hilton'].
            amenities: Amenity filters, e.g. ['pet_friendly', 'resort', 'pool'].
            weekend_only: Only return weekend stays (default False).
            sort: Sort order ('points', 'distance', 'price').
            page: Page number (1-based, default 1).
            page_size: Number of hotels per page (default 10).
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        loc = _build_hotel_location(
            city_or_label=location_name,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
        )

        req = HotelSearchRequest(
            location=loc,
            start_date=start_date,
            end_date=end_date,
            max_points=max_points,
            max_prices=max_prices,
            programs=programs,
            amenities=amenities,
            weekend_only=weekend_only,
            sort=sort,
            pagination=Pagination(page=page, page_size=page_size),
        )

        try:
            data = await pointsyeah_client.search_hotels(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_hotel_details(
        property_id: int,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Retrieve complete information for a specific hotel property.

        Returns property images, phone number, address, geolocation, room amenities, and policies.

        Args:
            property_id: PointsYeah hotel property ID (obtained from hotel search results).
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        req = HotelDetailRequest(property_id=property_id)
        try:
            data = await pointsyeah_client.get_hotel_details(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_hotel_calendar(
        property_id: int,
        month: str,
        fhr: bool = False,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Retrieve monthly daily award availability and cash pricing for a specific hotel.

        Returns daily points required, cash prices, and room types for each day of the month.

        Args:
            property_id: PointsYeah hotel property ID (from hotel search results).
            month: Month to inspect in YYYY-MM format (e.g. '2026-07').
            fhr: Query Fine Hotels & Resorts calendar data (default False).
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        req = HotelCalendarRequest(property_id=property_id, month=month, fhr=fhr)
        try:
            data = await pointsyeah_client.get_hotel_calendar(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_hotel_recommendations(
        location_name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        country_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sort: str = "points",
        page: int = 1,
        page_size: int = 10,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Get curated hotel award recommendations with high redemption value.

        Args:
            location_name: Destination name (e.g. 'Paris, France', 'Miami, FL').
            latitude: Optional latitude.
            longitude: Optional longitude.
            country_code: Two-letter ISO country code.
            start_date: Check-in date (YYYY-MM-DD).
            end_date: Check-out date (YYYY-MM-DD).
            sort: Sort criteria (default 'points').
            page: Page number (default 1).
            page_size: Results per page (default 10).
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        loc = _build_hotel_location(
            city_or_label=location_name,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
        )

        req = HotelRecommendRequest(
            location=loc,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            pagination=Pagination(page=page, page_size=page_size),
        )

        try:
            data = await pointsyeah_client.get_hotel_recommendations(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_hotel_map_distribution(
        location_name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        country_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_points: Optional[int] = None,
        max_prices: Optional[int] = None,
        programs: Optional[List[str]] = None,
        sort: Optional[str] = None,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Retrieve hotel counts grouped by country for map visualization around a destination.

        Args:
            location_name: Location label or destination.
            latitude: Optional latitude coordinate.
            longitude: Optional longitude coordinate.
            country_code: Country code.
            start_date: Check-in date.
            end_date: Check-out date.
            max_points: Max points.
            max_prices: Max cash price.
            programs: Hotel loyalty programs.
            sort: Sort order.
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        loc = _build_hotel_location(
            city_or_label=location_name,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
        )

        req = HotelMapRequest(
            location=loc,
            start_date=start_date,
            end_date=end_date,
            max_points=max_points,
            max_prices=max_prices,
            programs=programs,
            sort=sort,
        )

        try:
            data = await pointsyeah_client.get_hotel_map(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"
