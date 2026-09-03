"""
Weather service layer for AeroHealth.

Wraps two free, no-key APIs as specified in the project presentation:
  - Open-Meteo  (https://open-meteo.com)   — current + 72h forecast
  - NASA POWER  (https://power.larc.nasa.gov) — daily MERRA-2 reanalysis

Both services are designed to be called from Celery tasks and store
results directly into the Django ORM.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo variable names we request
OPEN_METEO_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "cloud_cover",
    "visibility",
    "weather_code",
    "boundary_layer_height",
]

OPEN_METEO_CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "cloud_cover",
    "visibility",
    "weather_code",
]

NASA_POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# NASA POWER parameter names (MERRA-2)
# T2M     = Temperature at 2 Metres
# T2MWET  = Wet Bulb Temperature at 2 Metres
# T2M_MAX = Maximum Temperature at 2 Metres
# T2M_MIN = Minimum Temperature at 2 Metres
# WS10M   = Wind Speed at 10 Metres
# WD10M   = Wind Direction at 10 Metres
# QV2M    = Specific Humidity at 2 Metres
# RH2M    = Relative Humidity at 2 Metres
# PRECTOTCORR = Precipitation Corrected
# ALLSKY_SFC_SW_DWN = All Sky Surface Shortwave Downward Irradiance
# PS      = Surface Pressure
# PBLH    = Planetary Boundary Layer Height
NASA_POWER_PARAMS = (
    "T2M,T2M_MAX,T2M_MIN,WS10M,WD10M,QV2M,RH2M,PRECTOTCORR,"
    "ALLSKY_SFC_SW_DWN,PS,PBLH"
)

REQUEST_TIMEOUT = 30  # seconds


# --------------------------------------------------------------------------- #
# Open-Meteo Service                                                           #
# --------------------------------------------------------------------------- #


class OpenMeteoService:
    """
    Fetches real-time and forecast weather data from Open-Meteo.

    Open-Meteo is free and requires no API key, as specified in the project.
    It provides:
      - Current conditions (updated every 15 min)
      - Hourly forecast up to 16 days (we use 72 h)
    """

    def fetch_current(self, latitude: float, longitude: float) -> dict[str, Any]:
        """
        Fetch current weather for a single point.

        Returns a flat dict ready to be passed to WeatherObservation.objects.create().
        Raises requests.RequestException on network / API errors.
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(OPEN_METEO_CURRENT_VARS),
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
        }

        logger.debug(
            "Open-Meteo current fetch: lat=%.4f lon=%.4f", latitude, longitude
        )
        response = requests.get(
            OPEN_METEO_BASE_URL, params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})
        current_units = data.get("current_units", {})

        # Parse the ISO-8601 time string that Open-Meteo returns
        observed_at = self._parse_utc_dt(current.get("time"))

        result = {
            "latitude": latitude,
            "longitude": longitude,
            "observed_at": observed_at,
            "temperature_2m": current.get("temperature_2m"),
            "relative_humidity_2m": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed_10m": current.get("wind_speed_10m"),
            "wind_direction_10m": current.get("wind_direction_10m"),
            "wind_gusts_10m": current.get("wind_gusts_10m"),
            "surface_pressure": current.get("surface_pressure"),
            "cloud_cover": current.get("cloud_cover"),
            "visibility": current.get("visibility"),
            "weather_code": current.get("weather_code"),
            "source": "open_meteo",
        }
        logger.info(
            "Open-Meteo current: (%.4f, %.4f) T=%.1f°C Wind=%.1f km/h @ %s",
            latitude,
            longitude,
            result["temperature_2m"] or 0,
            result["wind_speed_10m"] or 0,
            observed_at,
        )
        return result

    def fetch_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_hours: int = 72,
    ) -> list[dict[str, Any]]:
        """
        Fetch hourly weather forecast (up to 72 h) for a single point.

        Returns a list of dicts, one per hour, ready for
        WeatherForecast.objects.bulk_create().
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(OPEN_METEO_HOURLY_VARS),
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
            "forecast_hours": forecast_hours,
        }

        logger.debug(
            "Open-Meteo %dh forecast fetch: lat=%.4f lon=%.4f",
            forecast_hours,
            latitude,
            longitude,
        )
        response = requests.get(
            OPEN_METEO_BASE_URL, params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        generated_at = timezone.now()

        rows = []
        for i, time_str in enumerate(times):
            valid_time = self._parse_utc_dt(time_str)
            lead_hours = i + 1

            rows.append(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "forecast_generated_at": generated_at,
                    "valid_time": valid_time,
                    "lead_hours": lead_hours,
                    "temperature_2m": self._get(hourly, "temperature_2m", i),
                    "relative_humidity_2m": self._get(hourly, "relative_humidity_2m", i),
                    "precipitation": self._get(hourly, "precipitation", i),
                    "precipitation_probability": self._get(
                        hourly, "precipitation_probability", i
                    ),
                    "wind_speed_10m": self._get(hourly, "wind_speed_10m", i),
                    "wind_direction_10m": self._get(hourly, "wind_direction_10m", i),
                    "wind_gusts_10m": self._get(hourly, "wind_gusts_10m", i),
                    "surface_pressure": self._get(hourly, "surface_pressure", i),
                    "cloud_cover": self._get(hourly, "cloud_cover", i),
                    "visibility": self._get(hourly, "visibility", i),
                    "weather_code": self._get(hourly, "weather_code", i),
                    "boundary_layer_height": self._get(
                        hourly, "boundary_layer_height", i
                    ),
                    "source": "open_meteo",
                }
            )

        logger.info(
            "Open-Meteo forecast: (%.4f, %.4f) — %d hourly rows",
            latitude,
            longitude,
            len(rows),
        )
        return rows

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_utc_dt(time_str: str | None) -> datetime | None:
        """Parse Open-Meteo ISO-8601 time strings ('2024-01-01T12:00') to UTC datetime."""
        if not time_str:
            return None
        # Open-Meteo returns naive ISO strings when timezone=UTC
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt

    @staticmethod
    def _get(hourly: dict, key: str, index: int) -> Any:
        """Safely index into an Open-Meteo hourly variable list."""
        values = hourly.get(key)
        if values is None or index >= len(values):
            return None
        return values[index]


# --------------------------------------------------------------------------- #
# NASA POWER Service                                                           #
# --------------------------------------------------------------------------- #


class NASAPowerService:
    """
    Fetches daily MERRA-2 reanalysis data from the NASA POWER API.

    NASA POWER is free and requires no API key, as specified in the project.

    Typical use-cases in AeroHealth:
      - Fetch the last 365 days for a station to build training features
      - Nightly refresh for the previous day's reanalysis
    """

    def fetch_daily(
        self,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """
        Fetch daily reanalysis for a point over a date range.

        Returns a list of dicts (one per day) ready for
        NASAPowerReanalysis.objects.bulk_create() with update_conflicts=True.

        start_date and end_date are both inclusive.
        NASA POWER accepts dates in YYYYMMDD format.
        """
        params = {
            "parameters": NASA_POWER_PARAMS,
            "community": "RE",
            "longitude": longitude,
            "latitude": latitude,
            "start": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "format": "JSON",
            "header": "true",
            "time-standard": "UTC",
        }

        logger.debug(
            "NASA POWER fetch: lat=%.4f lon=%.4f %s → %s",
            latitude,
            longitude,
            start_date,
            end_date,
        )
        response = requests.get(
            NASA_POWER_BASE_URL, params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        try:
            param_data = data["properties"]["parameter"]
        except KeyError:
            logger.error("NASA POWER: unexpected response structure: %s", data)
            return []

        # All params share the same date keys in YYYYMMDD format
        dates = sorted(param_data.get("T2M", {}).keys())

        rows = []
        fetched_at = timezone.now()
        for date_str in dates:
            try:
                record_date = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                continue

            def pv(param: str) -> float | None:
                """Extract a parameter value, return None for fill value -999."""
                val = param_data.get(param, {}).get(date_str)
                if val is None or val == -999 or val == -999.0:
                    return None
                return float(val)

            rows.append(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "date": record_date,
                    "fetched_at": fetched_at,
                    "temperature_max": pv("T2M_MAX"),
                    "temperature_min": pv("T2M_MIN"),
                    "temperature_mean": pv("T2M"),
                    "wind_speed_10m_mean": pv("WS10M"),
                    "wind_direction_10m_mean": pv("WD10M"),
                    "specific_humidity": pv("QV2M"),
                    "relative_humidity": pv("RH2M"),
                    "precipitation": pv("PRECTOTCORR"),
                    "surface_shortwave_radiation": pv("ALLSKY_SFC_SW_DWN"),
                    "surface_pressure": pv("PS"),
                    "boundary_layer_height": pv("PBLH"),
                    "source": "nasa_power",
                }
            )

        logger.info(
            "NASA POWER: (%.4f, %.4f) — %d daily records fetched",
            latitude,
            longitude,
            len(rows),
        )
        return rows

    def fetch_yesterday(
        self, latitude: float, longitude: float
    ) -> list[dict[str, Any]]:
        """Convenience: fetch only the previous day's reanalysis."""
        yesterday = date.today() - timedelta(days=1)
        return self.fetch_daily(latitude, longitude, yesterday, yesterday)

    def fetch_last_n_days(
        self, latitude: float, longitude: float, n_days: int = 365
    ) -> list[dict[str, Any]]:
        """Convenience: fetch the last N days (default 1 year) of reanalysis."""
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=n_days - 1)
        return self.fetch_daily(latitude, longitude, start, end)
