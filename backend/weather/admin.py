"""
Django admin configuration for the AeroHealth weather app.

Registers WeatherObservation, WeatherForecast, and NASAPowerReanalysis
with useful list_display, filters, and search fields.
"""

from django.contrib import admin

from .models import NASAPowerReanalysis, WeatherForecast, WeatherObservation


@admin.register(WeatherObservation)
class WeatherObservationAdmin(admin.ModelAdmin):
    list_display = [
        "city",
        "latitude",
        "longitude",
        "observed_at",
        "temperature_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "relative_humidity_2m",
        "weather_code",
        "source",
    ]
    list_filter = ["source", "city"]
    search_fields = ["city"]
    ordering = ["-observed_at"]
    date_hierarchy = "observed_at"
    readonly_fields = ["fetched_at"]


@admin.register(WeatherForecast)
class WeatherForecastAdmin(admin.ModelAdmin):
    list_display = [
        "city",
        "latitude",
        "longitude",
        "valid_time",
        "lead_hours",
        "temperature_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "precipitation",
        "forecast_generated_at",
    ]
    list_filter = ["city", "source"]
    search_fields = ["city"]
    ordering = ["valid_time"]
    date_hierarchy = "valid_time"
    readonly_fields = ["forecast_generated_at"]


@admin.register(NASAPowerReanalysis)
class NASAPowerReanalysisAdmin(admin.ModelAdmin):
    list_display = [
        "city",
        "latitude",
        "longitude",
        "date",
        "temperature_mean",
        "wind_speed_10m_mean",
        "wind_direction_10m_mean",
        "relative_humidity",
        "precipitation",
        "source",
    ]
    list_filter = ["source", "city"]
    search_fields = ["city"]
    ordering = ["-date"]
    date_hierarchy = "date"
    readonly_fields = ["fetched_at"]
