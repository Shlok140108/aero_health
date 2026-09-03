"""
Celery tasks for the AeroHealth weather app.

Scheduled tasks (configured in CELERY_BEAT_SCHEDULE in settings.py):
  - fetch_weather_observations_task   : every 1 hour  → Open-Meteo current
  - fetch_weather_forecasts_task      : every 1 hour  → Open-Meteo 72h hourly
  - fetch_nasa_power_reanalysis_task  : every 24 hours → NASA POWER yesterday

All tasks are idempotent and safe to retry on failure.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

from .models import NASAPowerReanalysis, WeatherForecast, WeatherObservation
from .services import NASAPowerService, OpenMeteoService

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Station registry                                                              #
#                                                                              #
# Representative lat/lon for major Indian cities that have CPCB monitoring     #
# stations. Extend this list as needed — the AQI Forecast model (Model 2)     #
# needs weather data for every location it predicts air quality for.           #
# --------------------------------------------------------------------------- #

INDIA_WEATHER_STATIONS: list[dict] = [
    {"city": "New Delhi",    "lat": 28.6139,  "lon": 77.2090},
    {"city": "Mumbai",       "lat": 19.0760,  "lon": 72.8777},
    {"city": "Kolkata",      "lat": 22.5726,  "lon": 88.3639},
    {"city": "Chennai",      "lat": 13.0827,  "lon": 80.2707},
    {"city": "Bengaluru",    "lat": 12.9716,  "lon": 77.5946},
    {"city": "Hyderabad",    "lat": 17.3850,  "lon": 78.4867},
    {"city": "Ahmedabad",    "lat": 23.0225,  "lon": 72.5714},
    {"city": "Pune",         "lat": 18.5204,  "lon": 73.8567},
    {"city": "Jaipur",       "lat": 26.9124,  "lon": 75.7873},
    {"city": "Lucknow",      "lat": 26.8467,  "lon": 80.9462},
    {"city": "Kanpur",       "lat": 26.4499,  "lon": 80.3319},
    {"city": "Patna",        "lat": 25.5941,  "lon": 85.1376},
    {"city": "Bhopal",       "lat": 23.2599,  "lon": 77.4126},
    {"city": "Nagpur",       "lat": 21.1458,  "lon": 79.0882},
    {"city": "Visakhapatnam","lat": 17.6868,  "lon": 83.2185},
    {"city": "Amritsar",     "lat": 31.6340,  "lon": 74.8723},
    {"city": "Chandigarh",   "lat": 30.7333,  "lon": 76.7794},
    {"city": "Guwahati",     "lat": 26.1445,  "lon": 91.7362},
    {"city": "Ranchi",       "lat": 23.3441,  "lon": 85.3096},
    {"city": "Bhubaneswar",  "lat": 20.2961,  "lon": 85.8245},
    # Delhi-NCR sub-districts (stubble-burning corridor — high priority)
    {"city": "Gurgaon",      "lat": 28.4595,  "lon": 77.0266},
    {"city": "Faridabad",    "lat": 28.4089,  "lon": 77.3178},
    {"city": "Noida",        "lat": 28.5355,  "lon": 77.3910},
    {"city": "Ghaziabad",    "lat": 28.6692,  "lon": 77.4538},
]


# --------------------------------------------------------------------------- #
# Open-Meteo tasks                                                              #
# --------------------------------------------------------------------------- #


@shared_task(
    name="weather.fetch_weather_observations",
    bind=True,
    max_retries=3,
    default_retry_delay=120,  # 2 minutes between retries
)
def fetch_weather_observations_task(self) -> dict:
    """
    Fetch current weather from Open-Meteo for all INDIA_WEATHER_STATIONS.

    Runs every hour via Celery Beat.
    Stores results as WeatherObservation records.
    """
    service = OpenMeteoService()
    created_count = 0
    error_count = 0

    for station in INDIA_WEATHER_STATIONS:
        try:
            data = service.fetch_current(station["lat"], station["lon"])
            data["city"] = station["city"]
            WeatherObservation.objects.create(**data)
            created_count += 1
            logger.debug("Observation saved: %s", station["city"])
        except Exception as exc:
            error_count += 1
            logger.warning(
                "Failed to fetch Open-Meteo current for %s: %s",
                station["city"],
                exc,
            )

    logger.info(
        "fetch_weather_observations_task complete: %d saved, %d errors",
        created_count,
        error_count,
    )
    return {"created": created_count, "errors": error_count}


@shared_task(
    name="weather.fetch_weather_forecasts",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def fetch_weather_forecasts_task(self) -> dict:
    """
    Fetch 72-hour hourly weather forecast from Open-Meteo for all stations.

    Runs every hour via Celery Beat.
    Stores results as WeatherForecast records (72 rows per station per run).
    """
    service = OpenMeteoService()
    created_count = 0
    error_count = 0

    for station in INDIA_WEATHER_STATIONS:
        try:
            rows = service.fetch_forecast(
                station["lat"], station["lon"], forecast_hours=72
            )
            objs = [
                WeatherForecast(city=station["city"], **row)
                for row in rows
            ]
            with transaction.atomic():
                WeatherForecast.objects.bulk_create(objs, batch_size=100)
            created_count += len(objs)
            logger.debug(
                "Forecast saved: %s (%d rows)", station["city"], len(objs)
            )
        except Exception as exc:
            error_count += 1
            logger.warning(
                "Failed to fetch Open-Meteo forecast for %s: %s",
                station["city"],
                exc,
            )

    logger.info(
        "fetch_weather_forecasts_task complete: %d rows saved, %d station errors",
        created_count,
        error_count,
    )
    return {"created": created_count, "errors": error_count}


# --------------------------------------------------------------------------- #
# NASA POWER task                                                               #
# --------------------------------------------------------------------------- #


@shared_task(
    name="weather.fetch_nasa_power_reanalysis",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
)
def fetch_nasa_power_reanalysis_task(self) -> dict:
    """
    Fetch yesterday's NASA POWER MERRA-2 reanalysis for all stations.

    Runs once per day (e.g. 06:00 UTC) via Celery Beat.
    Uses upsert so re-running is safe and idempotent.
    """
    service = NASAPowerService()
    upserted_count = 0
    error_count = 0

    for station in INDIA_WEATHER_STATIONS:
        try:
            rows = service.fetch_yesterday(station["lat"], station["lon"])
            if not rows:
                continue

            objs = [
                NASAPowerReanalysis(city=station["city"], **row)
                for row in rows
            ]
            with transaction.atomic():
                NASAPowerReanalysis.objects.bulk_create(
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
            upserted_count += len(rows)
            logger.debug("NASA POWER upserted: %s", station["city"])
        except Exception as exc:
            error_count += 1
            logger.warning(
                "Failed to fetch NASA POWER for %s: %s", station["city"], exc
            )

    logger.info(
        "fetch_nasa_power_reanalysis_task complete: %d upserted, %d errors",
        upserted_count,
        error_count,
    )
    return {"upserted": upserted_count, "errors": error_count}


# --------------------------------------------------------------------------- #
# Historical backfill task (run manually / one-off)                            #
# --------------------------------------------------------------------------- #


@shared_task(
    name="weather.backfill_nasa_power",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def backfill_nasa_power_task(
    self,
    lat: float,
    lon: float,
    city: str = "",
    n_days: int = 365,
) -> dict:
    """
    One-off backfill task — fetches the last `n_days` of NASA POWER data
    for a single station. Useful for seeding a new station's history.

    Example Celery call:
        backfill_nasa_power_task.delay(28.6139, 77.2090, "New Delhi", 730)
    """
    service = NASAPowerService()
    try:
        rows = service.fetch_last_n_days(lat, lon, n_days=n_days)
    except Exception as exc:
        logger.error("NASA POWER backfill failed for (%s, %s): %s", lat, lon, exc)
        raise self.retry(exc=exc)

    if not rows:
        return {"upserted": 0}

    objs = [NASAPowerReanalysis(city=city, **row) for row in rows]
    with transaction.atomic():
        NASAPowerReanalysis.objects.bulk_create(
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

    logger.info("NASA POWER backfill done: %s — %d records", city or f"({lat},{lon})", len(rows))
    return {"upserted": len(rows)}
