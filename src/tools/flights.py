"""Flight award search and recommendation tools for PointsYeah MCP server."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional
from mcp.server.mcpserver import Context, MCPServer

from src.pointsyeah_client import pointsyeah_client, PointsYeahAPIError
from src.schemas import (
    FlightAggregateRequest,
    FlightFilterRangeRequest,
    FlightLocationFilter,
    FlightRecommendRequest,
    FlightSearchRequest,
    Pagination,
)


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


def register_flight_tools(server: MCPServer) -> None:
    """Register all flight-related tools onto the MCPServer."""

    @server.tool()
    async def search_flights(
        start_date: str,
        end_date: str,
        departure_airports: Optional[List[str]] = None,
        arrival_airports: Optional[List[str]] = None,
        departure_countries: Optional[List[str]] = None,
        arrival_countries: Optional[List[str]] = None,
        departure_continents: Optional[List[str]] = None,
        arrival_continents: Optional[List[str]] = None,
        cabins: Optional[List[Literal["Economy", "Premium", "Business", "First"]]] = None,
        sort: str = "-updated_at",
        stops: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_duration: Optional[int] = None,
        max_points: Optional[int] = None,
        min_points: Optional[int] = None,
        banks: Optional[List[str]] = None,
        programs: Optional[List[str]] = None,
        premium_cabin_percentage: Optional[int] = None,
        max_tax: Optional[float] = None,
        seats: int = 1,
        weekend_only: bool = False,
        page: int = 1,
        page_size: int = 18,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Search for award flight availability across 40+ airline loyalty programs.

        Returns real-time award pricing (miles, taxes in USD), flight cabins,
        and credit card transfer partner redemption details.

        Args:
            start_date: Start of search window (YYYY-MM-DD). PointsYeah explorer holds ~61 days forward.
            end_date: End of search window (YYYY-MM-DD).
            departure_airports: 3-letter IATA airport codes (e.g. ['JFK', 'EWR']).
            arrival_airports: 3-letter IATA airport codes (e.g. ['LHR', 'CDG']).
            departure_countries: 2-letter country codes (e.g. ['US']).
            arrival_countries: 2-letter country codes (e.g. ['GB', 'FR']).
            departure_continents: Continent codes (e.g. ['NA', 'EU', 'AS']).
            arrival_continents: Continent codes (e.g. ['EU']).
            cabins: Cabin classes: 'Economy', 'Premium', 'Business', 'First'. Default: ['Economy'].
            sort: Sort order ('miles', '-miles', 'tax', '-tax', 'duration', '-duration', '-updated_at').
            stops: Max stops (0 for nonstop). Omit for any.
            max_duration: Maximum flight duration in minutes.
            min_duration: Minimum flight duration in minutes.
            max_points: Maximum miles/points required.
            min_points: Minimum miles/points required.
            banks: Filter by bank transfer programs (e.g. ['Chase', 'Amex', 'Bilt', 'Capital One', 'Citi']).
            programs: Filter by airline loyalty programs (e.g. ['AS', 'UA', 'AA', 'DL', 'VS', 'AF']).
            premium_cabin_percentage: Min % in premium cabin (0-100) when Business/First is selected.
            max_tax: Maximum tax in USD.
            seats: Number of passenger seats required (1-9, default 1).
            weekend_only: Only return weekend flights (default False).
            page: Pagination page number (1-based, default 1).
            page_size: Results per page (default 18).
            pointsyeah_api_key: Optional personal PointsYeah API key if not using server default.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        dep_filter = FlightLocationFilter(
            airports=departure_airports or [],
            countries=departure_countries or [],
            continents=departure_continents or [],
        )
        arr_filter = FlightLocationFilter(
            airports=arrival_airports or [],
            countries=arrival_countries or [],
            continents=arrival_continents or [],
        )

        # Validate that at least one departure and arrival field is populated
        if not (dep_filter.airports or dep_filter.countries or dep_filter.continents):
            return "Error: At least one departure location (e.g. departure_airports=['JFK']) must be provided."
        if not (arr_filter.airports or arr_filter.countries or arr_filter.continents):
            return "Error: At least one arrival location (e.g. arrival_airports=['LHR']) must be provided."

        req = FlightSearchRequest(
            departure=dep_filter,
            arrival=arr_filter,
            start_date=start_date,
            end_date=end_date,
            cabins=cabins or ["Economy"],
            sort=sort,
            stops=stops,
            max_duration=max_duration,
            min_duration=min_duration,
            max_points=max_points,
            min_points=min_points,
            banks=banks,
            programs=programs,
            premium_cabin_percentage=premium_cabin_percentage,
            max_tax=max_tax,
            seats=seats,
            weekend_only=weekend_only,
            pagination=Pagination(page=page, page_size=page_size),
        )

        try:
            data = await pointsyeah_client.search_flights(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_flight_route_recommendations(
        departure_airport: Optional[str] = None,
        arrival_airport: Optional[str] = None,
        today: Optional[str] = None,
        cabins: Optional[List[str]] = None,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Get curated high-value award flight route recommendations.

        Returns popular routes with good redemption values based on departure location.

        Args:
            departure_airport: 3-letter IATA code (e.g. 'LAX'). Omit to search from anywhere.
            arrival_airport: 3-letter IATA code (e.g. 'JFK'). Omit to recommend routes anywhere.
            today: Reference date for recommendations (YYYY-MM-DD). Defaults to tomorrow.
            cabins: Cabin classes to filter by, e.g. ['Economy', 'Business'].
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        dep: Dict[str, Any] = (
            {"airport": departure_airport.upper()}
            if departure_airport
            else {"anywhere": True}
        )
        arr: Dict[str, Any] = (
            {"airport": arrival_airport.upper()}
            if arrival_airport
            else {"anywhere": True}
        )

        req = FlightRecommendRequest(
            departure=dep,
            arrival=arr,
            today=today,
            cabins=cabins,
        )

        try:
            data = await pointsyeah_client.get_flight_recommendations(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_flight_search_aggregates(
        start_date: str,
        end_date: str,
        group_by: Literal["arrival_airport", "departure_airport"],
        departure_airports: Optional[List[str]] = None,
        arrival_airports: Optional[List[str]] = None,
        departure_countries: Optional[List[str]] = None,
        arrival_countries: Optional[List[str]] = None,
        departure_continents: Optional[List[str]] = None,
        arrival_continents: Optional[List[str]] = None,
        cabins: Optional[List[str]] = None,
        sort: str = "miles",
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Retrieve aggregated flight award search results for broad exploration or maps.

        Groups results by arrival or departure airport with lowest points found.

        Args:
            start_date: Start of search window (YYYY-MM-DD).
            end_date: End of search window (YYYY-MM-DD).
            group_by: Aggregation dimension ('arrival_airport' or 'departure_airport').
            departure_airports: List of departure airport codes.
            arrival_airports: List of arrival airport codes.
            departure_countries: List of departure country codes.
            arrival_countries: List of arrival country codes.
            departure_continents: Continent codes (e.g. ['EU']).
            arrival_continents: Continent codes.
            cabins: Cabin classes.
            sort: Sort order (e.g. 'miles').
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        dep_filter = FlightLocationFilter(
            airports=departure_airports or [],
            countries=departure_countries or [],
            continents=departure_continents or [],
        )
        arr_filter = FlightLocationFilter(
            airports=arrival_airports or [],
            countries=arrival_countries or [],
            continents=arrival_continents or [],
        )

        req = FlightAggregateRequest(
            departure=dep_filter,
            arrival=arr_filter,
            start_date=start_date,
            end_date=end_date,
            cabins=cabins or ["Economy"],
            sort=sort,
            group_by=group_by,
        )

        try:
            data = await pointsyeah_client.get_flight_aggregates(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_total_flight_count(
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Retrieve the total count of award flights currently indexed in the PointsYeah explorer database.

        Args:
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)
        try:
            data = await pointsyeah_client.get_flight_count(api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"

    @server.tool()
    async def get_flight_filter_ranges(
        start_date: str,
        end_date: str,
        departure_airports: Optional[List[str]] = None,
        arrival_airports: Optional[List[str]] = None,
        cabins: Optional[List[str]] = None,
        pointsyeah_api_key: Optional[str] = None,
        ctx: Optional[Context] = None,
    ) -> str:
        """Get the min/max range of filter values (points, tax, duration) for a given route context.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            departure_airports: Departure airport codes.
            arrival_airports: Arrival airport codes.
            cabins: Cabin classes.
            pointsyeah_api_key: Optional personal PointsYeah API key.
        """
        api_key = _extract_api_key(pointsyeah_api_key, ctx)

        req = FlightFilterRangeRequest(
            departure=FlightLocationFilter(airports=departure_airports or []),
            arrival=FlightLocationFilter(airports=arrival_airports or []),
            start_date=start_date,
            end_date=end_date,
            cabins=cabins or ["Economy"],
        )

        try:
            data = await pointsyeah_client.get_flight_filter_ranges(req, api_key=api_key)
            return json.dumps(data, indent=2)
        except PointsYeahAPIError as exc:
            return f"PointsYeah API Error: {exc}"
