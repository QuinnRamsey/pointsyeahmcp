"""Pydantic data schemas for PointsYeah API requests and responses."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Flight Schemas
# ============================================================================

class FlightLocationFilter(BaseModel):
    """Geographic filter for flight departure or arrival."""

    airports: List[str] = Field(
        default_factory=list,
        description="List of 3-letter IATA airport codes, e.g. ['JFK', 'LAX']",
    )
    countries: List[str] = Field(
        default_factory=list,
        description="List of 2-letter ISO country codes, e.g. ['US', 'GB']",
    )
    continents: List[str] = Field(
        default_factory=list,
        description="List of continent codes, e.g. ['NA', 'EU', 'AS']",
    )
    regions: List[str] = Field(
        default_factory=list,
        description="Region identifiers",
    )
    states: List[str] = Field(
        default_factory=list,
        description="US state codes, e.g. ['CA', 'NY']",
    )


class Pagination(BaseModel):
    """Pagination parameters."""

    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(default=18, ge=1, le=100, description="Results per page")


class FlightSearchRequest(BaseModel):
    """Payload for POST /explorer/search."""

    departure: FlightLocationFilter = Field(
        ..., description="Departure location filter. At least one sub-field should be populated."
    )
    arrival: FlightLocationFilter = Field(
        ..., description="Arrival location filter. Same structure as departure."
    )
    start_date: str = Field(
        ..., description="Start of search window in YYYY-MM-DD format."
    )
    end_date: str = Field(
        ..., description="End of search window in YYYY-MM-DD format."
    )
    cabins: List[Literal["Economy", "Premium", "Business", "First"]] = Field(
        default=["Economy"],
        description="Cabin classes to filter by. Defaults to ['Economy'].",
    )
    sort: str = Field(
        default="-updated_at",
        description="Sort order. Prefix with - for descending. Options: miles, -miles, tax, -tax, duration, -duration, -updated_at.",
    )
    stops: Optional[int] = Field(
        default=None, description="Maximum number of stops (e.g. 0 for nonstop). Omit for any."
    )
    max_duration: Optional[int] = Field(
        default=None, description="Maximum flight duration in minutes."
    )
    min_duration: Optional[int] = Field(
        default=None, description="Minimum flight duration in minutes."
    )
    max_points: Optional[int] = Field(
        default=None, description="Maximum miles/points required."
    )
    min_points: Optional[int] = Field(
        default=None, description="Minimum miles/points required."
    )
    banks: Optional[List[str]] = Field(
        default=None,
        description="Bank loyalty programs to filter by, e.g. ['Chase', 'Amex', 'Bilt', 'Capital One', 'Citi'].",
    )
    programs: Optional[List[str]] = Field(
        default=None,
        description="Airline loyalty programs to filter by, e.g. ['AS', 'UA', 'AA', 'DL'].",
    )
    premium_cabin_percentage: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Minimum premium cabin percentage (0-100). Only applies when Business or First is selected.",
    )
    trip: Optional[str] = Field(
        default=None, description="Type of travel filter (e.g., 'oneway')."
    )
    max_tax: Optional[float] = Field(
        default=None, description="Maximum tax amount in USD."
    )
    min_tax: Optional[float] = Field(
        default=None, description="Minimum tax amount in USD."
    )
    seats: int = Field(
        default=1, ge=1, le=9, description="Number of passenger seats required (1-9)."
    )
    weekend_only: bool = Field(
        default=False, description="Only return weekend departures."
    )
    collection: bool = Field(
        default=False, description="Include partner collection results."
    )
    pagination: Pagination = Field(
        default_factory=Pagination, description="Pagination controls."
    )


class FlightAggregateRequest(BaseModel):
    """Payload for POST /explorer/search/aggregate."""

    departure: FlightLocationFilter
    arrival: FlightLocationFilter
    start_date: str
    end_date: str
    cabins: List[str] = Field(default=["Economy"])
    sort: str = Field(default="miles")
    group_by: Literal["arrival_airport", "departure_airport"] = Field(
        default="arrival_airport",
        description="Aggregation dimension: 'arrival_airport' or 'departure_airport'.",
    )
    collection: bool = Field(default=False)
    pagination: Pagination = Field(default_factory=lambda: Pagination(page=1, page_size=9999))


class FlightRecommendRequest(BaseModel):
    """Payload for POST /explorer/recommend."""

    departure: Dict[str, Any] = Field(
        ...,
        description="Departure location. Can be {'airport': 'LAX'} or {'anywhere': True}.",
    )
    arrival: Dict[str, Any] = Field(
        default_factory=lambda: {"anywhere": True},
        description="Arrival location. Default is {'anywhere': True}.",
    )
    today: Optional[str] = Field(
        default=None,
        description="Reference date for recommendations, YYYY-MM-DD. Defaults to tomorrow.",
    )
    cabins: Optional[List[str]] = Field(
        default=None, description="Cabin classes to filter by."
    )


class FlightFilterRangeRequest(BaseModel):
    """Payload for POST /explorer/get_filter_range."""

    departure: FlightLocationFilter
    arrival: FlightLocationFilter
    start_date: str
    end_date: str
    cabins: List[str] = Field(default=["Economy"])


# ============================================================================
# Hotel Schemas
# ============================================================================

class HotelLocation(BaseModel):
    """Location specification for hotel searches."""

    label: str = Field(..., description="Display label, e.g. 'New York, NY'")
    value: str = Field(..., description="Location value, e.g. 'New York, NY'")
    longitude: float = Field(..., description="Longitude coordinate")
    latitude: float = Field(..., description="Latitude coordinate")
    distance: int = Field(
        default=30000, description="Search radius in meters. Default is 30,000m (30km)."
    )
    dest_type: str = Field(
        default="city", description="Destination type: 'city', 'country', or 'airport'."
    )
    country_code: str = Field(
        default="US", description="Two-letter ISO country code, e.g. 'US'."
    )


class HotelSearchRequest(BaseModel):
    """Payload for POST /hotel/explorer/search."""

    location: HotelLocation = Field(..., description="Search location and coordinates.")
    start_date: Optional[str] = Field(
        default=None, description="Check-in date in YYYY-MM-DD format."
    )
    end_date: Optional[str] = Field(
        default=None, description="Check-out date in YYYY-MM-DD format."
    )
    weekend_only: bool = Field(
        default=False, description="Only return weekend stays."
    )
    holiday_only: bool = Field(
        default=False, description="Only return holiday stays."
    )
    max_points: int = Field(
        default=200000, description="Maximum points required."
    )
    max_prices: int = Field(
        default=5000, description="Maximum cash price in USD."
    )
    amenities: Optional[List[str]] = Field(
        default=None, description="Amenity filters (e.g. ['pet_friendly', 'resort'])."
    )
    programs: Optional[List[str]] = Field(
        default=None, description="Hotel loyalty programs (e.g. ['ihg', 'hyatt', 'marriott', 'hilton'])."
    )
    brands: Optional[List[str]] = Field(
        default=None, description="Hotel brand filters."
    )
    sort: str = Field(
        default="points", description="Sort order (e.g. 'points', 'distance', 'price')."
    )
    pagination: Pagination = Field(
        default_factory=lambda: Pagination(page=1, page_size=10)
    )


class HotelDetailRequest(BaseModel):
    """Payload for POST /hotel/detail."""

    property_id: int = Field(
        ..., description="Hotel property ID from search results."
    )


class HotelCalendarRequest(BaseModel):
    """Payload for POST /hotel/explorer/calendar/v2."""

    property_id: int = Field(
        ..., description="Hotel property ID from search results."
    )
    month: str = Field(
        ..., description="Month to query in YYYY-MM format, e.g. '2026-07'."
    )
    fhr: bool = Field(
        default=False, description="Query Fine Hotels & Resorts calendar data."
    )


class HotelMapRequest(BaseModel):
    """Payload for POST /hotel/explorer/map."""

    location: HotelLocation
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_points: Optional[int] = None
    max_prices: Optional[int] = None
    programs: Optional[List[str]] = None
    sort: Optional[str] = None


class HotelRecommendRequest(BaseModel):
    """Payload for POST /hotel/explorer/recommend."""

    location: HotelLocation
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort: str = Field(default="points")
    pagination: Pagination = Field(default_factory=lambda: Pagination(page=1, page_size=10))
