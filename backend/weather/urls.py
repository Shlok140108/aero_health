"""
URL patterns for the AeroHealth weather app.

Mounted at /api/weather/ from the root urls.py.

Endpoints:
  GET  /api/weather/observations/          – list stored Open-Meteo observations
  GET  /api/weather/observations/current/  – live current weather from Open-Meteo
  GET  /api/weather/forecast/              – list stored 72h hourly forecast
  GET  /api/weather/forecast/latest/       – latest (or fresh) 72h forecast
  GET  /api/weather/reanalysis/            – list NASA POWER reanalysis records
  POST /api/weather/reanalysis/fetch/      – trigger on-demand NASA POWER fetch
"""

from django.urls import path

from .views import (
    NASAPowerFetchView,
    NASAPowerReanalysisListView,
    WeatherCurrentLiveFetchView,
    WeatherForecastLatestView,
    WeatherForecastListView,
    WeatherObservationListView,
)

app_name = "weather"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Open-Meteo — Current weather observations                           #
    # ------------------------------------------------------------------ #
    path(
        "observations/",
        WeatherObservationListView.as_view(),
        name="observations-list",
    ),
    path(
        "observations/current/",
        WeatherCurrentLiveFetchView.as_view(),
        name="observations-current-live",
    ),
    # ------------------------------------------------------------------ #
    # Open-Meteo — 72-hour hourly forecast                                #
    # ------------------------------------------------------------------ #
    path(
        "forecast/",
        WeatherForecastListView.as_view(),
        name="forecast-list",
    ),
    path(
        "forecast/latest/",
        WeatherForecastLatestView.as_view(),
        name="forecast-latest",
    ),
    # ------------------------------------------------------------------ #
    # NASA POWER — Daily MERRA-2 reanalysis                               #
    # ------------------------------------------------------------------ #
    path(
        "reanalysis/",
        NASAPowerReanalysisListView.as_view(),
        name="reanalysis-list",
    ),
    path(
        "reanalysis/fetch/",
        NASAPowerFetchView.as_view(),
        name="reanalysis-fetch",
    ),
]
