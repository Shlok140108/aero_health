"""
DRF serializers for the AeroHealth weather app.

Covers:
  - WeatherObservationSerializer  (Open-Meteo current)
  - WeatherForecastSerializer     (Open-Meteo 72h hourly)
  - NASAPowerReanalysisSerializer (NASA POWER daily reanalysis)
"""

from rest_framework import serializers

from .models import NASAPowerReanalysis, WeatherForecast, WeatherObservation

# WMO weather code → human-readable description (subset of the full table)
WMO_CODE_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    99: "Thunderstorm with hail",
}

COMPASS_SECTORS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]


def degrees_to_compass(degrees: float | None) -> str | None:
    """Convert meteorological wind direction in degrees to compass abbreviation."""
    if degrees is None:
        return None
    index = round(degrees / 22.5) % 16
    return COMPASS_SECTORS[index]


# --------------------------------------------------------------------------- #
# WeatherObservation                                                           #
# --------------------------------------------------------------------------- #


class WeatherObservationSerializer(serializers.ModelSerializer):
    """Serializer for real-time Open-Meteo observations."""

    wind_direction_compass = serializers.SerializerMethodField(
        help_text="Compass abbreviation derived from wind_direction_10m"
    )
    weather_description = serializers.SerializerMethodField(
        help_text="Human-readable WMO weather code description"
    )

    class Meta:
        model = WeatherObservation
        fields = [
            "id",
            "latitude",
            "longitude",
            "city",
            "observed_at",
            "fetched_at",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_direction_compass",
            "wind_gusts_10m",
            "surface_pressure",
            "cloud_cover",
            "visibility",
            "weather_code",
            "weather_description",
            "source",
        ]
        read_only_fields = fields

    def get_wind_direction_compass(self, obj: WeatherObservation) -> str | None:
        return degrees_to_compass(obj.wind_direction_10m)

    def get_weather_description(self, obj: WeatherObservation) -> str | None:
        if obj.weather_code is None:
            return None
        return WMO_CODE_DESCRIPTIONS.get(obj.weather_code, f"Code {obj.weather_code}")


# --------------------------------------------------------------------------- #
# WeatherForecast                                                              #
# --------------------------------------------------------------------------- #


class WeatherForecastSerializer(serializers.ModelSerializer):
    """Serializer for hourly 72-hour Open-Meteo forecast rows."""

    wind_direction_compass = serializers.SerializerMethodField()
    weather_description = serializers.SerializerMethodField()

    class Meta:
        model = WeatherForecast
        fields = [
            "id",
            "latitude",
            "longitude",
            "city",
            "forecast_generated_at",
            "valid_time",
            "lead_hours",
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "precipitation_probability",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_direction_compass",
            "wind_gusts_10m",
            "surface_pressure",
            "cloud_cover",
            "visibility",
            "weather_code",
            "weather_description",
            "boundary_layer_height",
            "source",
        ]
        read_only_fields = fields

    def get_wind_direction_compass(self, obj: WeatherForecast) -> str | None:
        return degrees_to_compass(obj.wind_direction_10m)

    def get_weather_description(self, obj: WeatherForecast) -> str | None:
        if obj.weather_code is None:
            return None
        return WMO_CODE_DESCRIPTIONS.get(obj.weather_code, f"Code {obj.weather_code}")


# --------------------------------------------------------------------------- #
# NASAPowerReanalysis                                                          #
# --------------------------------------------------------------------------- #


class NASAPowerReanalysisSerializer(serializers.ModelSerializer):
    """Serializer for NASA POWER daily reanalysis records."""

    wind_direction_compass = serializers.SerializerMethodField()

    class Meta:
        model = NASAPowerReanalysis
        fields = [
            "id",
            "latitude",
            "longitude",
            "city",
            "date",
            "fetched_at",
            "temperature_max",
            "temperature_min",
            "temperature_mean",
            "wind_speed_10m_mean",
            "wind_direction_10m_mean",
            "wind_direction_compass",
            "specific_humidity",
            "relative_humidity",
            "precipitation",
            "surface_shortwave_radiation",
            "surface_pressure",
            "boundary_layer_height",
            "source",
        ]
        read_only_fields = fields

    def get_wind_direction_compass(self, obj: NASAPowerReanalysis) -> str | None:
        return degrees_to_compass(obj.wind_direction_10m_mean)
