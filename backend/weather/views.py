"""
DRF views for the AeroHealth weather app.

Endpoints:
  GET /api/weather/observations/          – list stored Open-Meteo observations
  GET /api/weather/observations/current/  – live fetch from Open-Meteo (no DB hit)
  GET /api/weather/forecast/              – list stored 72h hourly forecast rows
  GET /api/weather/forecast/latest/       – latest forecast for a lat/lon pair
  GET /api/weather/reanalysis/            – list NASA POWER reanalysis records
  POST /api/weather/reanalysis/fetch/     – trigger immediate NASA POWER fetch
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NASAPowerReanalysis, WeatherForecast, WeatherObservation
from .serializers import (
    NASAPowerReanalysisSerializer,
    WeatherForecastSerializer,
    WeatherObservationSerializer,
)
from .services import NASAPowerService, OpenMeteoService


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _parse_lat_lon(request) -> tuple[float, float]:
    """
    Extract and validate ?lat= and ?lon= query parameters.
    Raises ValidationError (HTTP 400) if missing or unparseable.
    """
    try:
        lat = float(request.query_params["lat"])
        lon = float(request.query_params["lon"])
    except KeyError as exc:
        raise ValidationError(
            {"detail": "Both 'lat' and 'lon' query parameters are required."}
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"detail": "'lat' and 'lon' must be valid floating-point numbers."}
        ) from exc

    if not (-90 <= lat <= 90):
        raise ValidationError({"lat": "Must be between -90 and 90."})
    if not (-180 <= lon <= 180):
        raise ValidationError({"lon": "Must be between -180 and 180."})

    return lat, lon


# --------------------------------------------------------------------------- #
# Weather Observations (Open-Meteo current)                                   #
# --------------------------------------------------------------------------- #


class WeatherObservationListView(APIView):
    """
    GET /api/weather/observations/

    Returns stored Open-Meteo current-weather snapshots.

    Query parameters:
      lat      – filter by latitude  (exact match)
      lon      – filter by longitude (exact match)
      city     – filter by city name (case-insensitive contains)
      from_dt  – ISO-8601 start datetime (inclusive), e.g. 2024-01-01T00:00:00Z
      to_dt    – ISO-8601 end datetime   (inclusive)
      limit    – max records to return (default 100, max 500)
    """

    def get(self, request):
        qs = WeatherObservation.objects.all()

        if lat := request.query_params.get("lat"):
            qs = qs.filter(latitude=float(lat))
        if lon := request.query_params.get("lon"):
            qs = qs.filter(longitude=float(lon))
        if city := request.query_params.get("city"):
            qs = qs.filter(city__icontains=city)
        if from_dt := request.query_params.get("from_dt"):
            qs = qs.filter(observed_at__gte=from_dt)
        if to_dt := request.query_params.get("to_dt"):
            qs = qs.filter(observed_at__lte=to_dt)

        limit = min(int(request.query_params.get("limit", 100)), 500)
        qs = qs[:limit]

        serializer = WeatherObservationSerializer(qs, many=True)
        return Response(serializer.data)


class WeatherCurrentLiveFetchView(APIView):
    """
    GET /api/weather/observations/current/?lat=<lat>&lon=<lon>

    Fetches a live current-weather reading directly from Open-Meteo for
    the requested coordinates, saves it to the DB, and returns it.

    No API key required — Open-Meteo is free.
    """

    def get(self, request):
        lat, lon = _parse_lat_lon(request)
        city = request.query_params.get("city", "")

        service = OpenMeteoService()
        try:
            data = service.fetch_current(lat, lon)
        except Exception as exc:
            return Response(
                {"detail": f"Open-Meteo fetch failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        data["city"] = city
        obs = WeatherObservation.objects.create(**data)
        serializer = WeatherObservationSerializer(obs)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------- #
# Weather Forecast (Open-Meteo 72h)                                           #
# --------------------------------------------------------------------------- #


class WeatherForecastListView(APIView):
    """
    GET /api/weather/forecast/

    Returns stored hourly Open-Meteo forecast rows.

    Query parameters:
      lat        – filter by latitude  (exact)
      lon        – filter by longitude (exact)
      city       – filter by city (case-insensitive contains)
      from_time  – ISO-8601 start of valid_time range
      to_time    – ISO-8601 end of valid_time range
      lead_max   – max lead hours (e.g. 72)
      limit      – max rows (default 200, max 1000)
    """

    def get(self, request):
        qs = WeatherForecast.objects.all()

        if lat := request.query_params.get("lat"):
            qs = qs.filter(latitude=float(lat))
        if lon := request.query_params.get("lon"):
            qs = qs.filter(longitude=float(lon))
        if city := request.query_params.get("city"):
            qs = qs.filter(city__icontains=city)
        if from_time := request.query_params.get("from_time"):
            qs = qs.filter(valid_time__gte=from_time)
        if to_time := request.query_params.get("to_time"):
            qs = qs.filter(valid_time__lte=to_time)
        if lead_max := request.query_params.get("lead_max"):
            qs = qs.filter(lead_hours__lte=int(lead_max))

        limit = min(int(request.query_params.get("limit", 200)), 1000)
        qs = qs[:limit]

        serializer = WeatherForecastSerializer(qs, many=True)
        return Response(serializer.data)


class WeatherForecastLatestView(APIView):
    """
    GET /api/weather/forecast/latest/?lat=<lat>&lon=<lon>

    Returns the most recently generated 72-hour forecast for a location.
    If no stored forecast exists (or it is >2h stale), fetches live from
    Open-Meteo, persists, and returns fresh data.
    """

    STALE_THRESHOLD_HOURS = 2

    def get(self, request):
        lat, lon = _parse_lat_lon(request)
        city = request.query_params.get("city", "")

        # Try to return a fresh stored forecast
        cutoff = timezone.now() - timedelta(hours=self.STALE_THRESHOLD_HOURS)
        rows = WeatherForecast.objects.filter(
            latitude=lat,
            longitude=lon,
            forecast_generated_at__gte=cutoff,
        ).order_by("valid_time")

        if rows.exists():
            serializer = WeatherForecastSerializer(rows, many=True)
            return Response(
                {
                    "source": "cache",
                    "generated_at": rows.first().forecast_generated_at,
                    "count": rows.count(),
                    "forecast": serializer.data,
                }
            )

        # Stale or missing — fetch fresh
        service = OpenMeteoService()
        try:
            forecast_rows = service.fetch_forecast(lat, lon, forecast_hours=72)
        except Exception as exc:
            return Response(
                {"detail": f"Open-Meteo forecast fetch failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        objs = [
            WeatherForecast(city=city, **row) for row in forecast_rows
        ]
        created = WeatherForecast.objects.bulk_create(objs, batch_size=100)
        serializer = WeatherForecastSerializer(created, many=True)
        return Response(
            {
                "source": "live",
                "generated_at": timezone.now(),
                "count": len(created),
                "forecast": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------- #
# NASA POWER Reanalysis                                                        #
# --------------------------------------------------------------------------- #


class NASAPowerReanalysisListView(APIView):
    """
    GET /api/weather/reanalysis/

    Returns stored NASA POWER daily reanalysis records.

    Query parameters:
      lat        – filter by latitude  (exact)
      lon        – filter by longitude (exact)
      city       – filter by city (case-insensitive contains)
      from_date  – ISO date (YYYY-MM-DD) inclusive
      to_date    – ISO date (YYYY-MM-DD) inclusive
      limit      – max rows (default 365, max 3650)
    """

    def get(self, request):
        qs = NASAPowerReanalysis.objects.all()

        if lat := request.query_params.get("lat"):
            qs = qs.filter(latitude=float(lat))
        if lon := request.query_params.get("lon"):
            qs = qs.filter(longitude=float(lon))
        if city := request.query_params.get("city"):
            qs = qs.filter(city__icontains=city)
        if from_date := request.query_params.get("from_date"):
            qs = qs.filter(date__gte=from_date)
        if to_date := request.query_params.get("to_date"):
            qs = qs.filter(date__lte=to_date)

        limit = min(int(request.query_params.get("limit", 365)), 3650)
        qs = qs[:limit]

        serializer = NASAPowerReanalysisSerializer(qs, many=True)
        return Response(serializer.data)


class NASAPowerFetchView(APIView):
    """
    POST /api/weather/reanalysis/fetch/

    Triggers an immediate NASA POWER reanalysis fetch for a location
    and date range. Useful for seeding data or filling gaps.

    Request body (JSON):
      {
        "lat":        28.6139,
        "lon":        77.2090,
        "city":       "New Delhi",        (optional)
        "start_date": "2024-01-01",       (YYYY-MM-DD)
        "end_date":   "2024-12-31"        (YYYY-MM-DD)
      }

    Returns the number of records created/updated.
    """

    def post(self, request):
        data = request.data

        try:
            lat = float(data["lat"])
            lon = float(data["lon"])
            start_date = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
        except KeyError as exc:
            raise ValidationError(
                {"detail": f"Missing required field: {exc}"}
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        if start_date > end_date:
            raise ValidationError({"detail": "start_date must be <= end_date."})

        city = data.get("city", "")

        service = NASAPowerService()
        try:
            rows = service.fetch_daily(lat, lon, start_date, end_date)
        except Exception as exc:
            return Response(
                {"detail": f"NASA POWER fetch failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not rows:
            return Response({"records_saved": 0})

        # Upsert: update existing records if they already exist
        objs = [NASAPowerReanalysis(city=city, **row) for row in rows]
        result = NASAPowerReanalysis.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["latitude", "longitude", "date"],
            update_fields=[
                "temperature_max", "temperature_min", "temperature_mean",
                "wind_speed_10m_mean", "wind_direction_10m_mean",
                "specific_humidity", "relative_humidity", "precipitation",
                "surface_shortwave_radiation", "surface_pressure",
                "boundary_layer_height", "fetched_at",
            ],
            batch_size=200,
        )
        return Response(
            {"records_saved": len(result)},
            status=status.HTTP_201_CREATED,
        )
