"""
Weather models for AeroHealth.

Data sources (as per project specification):
  - Open-Meteo  : wind, humidity, rain, temperature  (free, no API key)
  - NASA POWER  : meteorological reanalysis           (free, no API key)

These fields feed the AQI Forecast model (Model 2) which uses
wind speed & direction to predict pollutant dispersion 24-72 h ahead.
"""

from django.db import models
from django.utils import timezone


class WeatherObservation(models.Model):
    """
    Real-time / near-real-time weather snapshot fetched from Open-Meteo.

    Fetched every hour via Celery beat for each monitored location in India.
    Wind fields are the primary inputs to the AQI dispersion forecast.
    """

    # ------------------------------------------------------------------ #
    # Location                                                             #
    # ------------------------------------------------------------------ #
    latitude = models.FloatField(help_text="Decimal degrees, WGS-84")
    longitude = models.FloatField(help_text="Decimal degrees, WGS-84")
    city = models.CharField(
        max_length=128,
        blank=True,
        help_text="Human-readable city / district name (optional)",
    )

    # ------------------------------------------------------------------ #
    # Observation timestamp                                                #
    # ------------------------------------------------------------------ #
    observed_at = models.DateTimeField(
        help_text="UTC time the observation was valid for (from Open-Meteo)"
    )
    fetched_at = models.DateTimeField(
        default=timezone.now,
        help_text="UTC time this record was written to the DB",
    )

    # ------------------------------------------------------------------ #
    # Core meteorological parameters (Open-Meteo current weather)         #
    # ------------------------------------------------------------------ #
    temperature_2m = models.FloatField(
        null=True, blank=True, help_text="Air temperature at 2 m height (°C)"
    )
    relative_humidity_2m = models.FloatField(
        null=True, blank=True, help_text="Relative humidity at 2 m (%)"
    )
    precipitation = models.FloatField(
        null=True, blank=True, help_text="Precipitation in the last hour (mm)"
    )
    wind_speed_10m = models.FloatField(
        null=True, blank=True, help_text="Wind speed at 10 m height (km/h)"
    )
    wind_direction_10m = models.FloatField(
        null=True, blank=True, help_text="Wind direction at 10 m, meteorological (°)"
    )
    wind_gusts_10m = models.FloatField(
        null=True, blank=True, help_text="Wind gusts at 10 m (km/h)"
    )
    surface_pressure = models.FloatField(
        null=True, blank=True, help_text="Surface air pressure (hPa)"
    )
    cloud_cover = models.FloatField(
        null=True, blank=True, help_text="Total cloud cover (%)"
    )
    visibility = models.FloatField(
        null=True, blank=True, help_text="Horizontal visibility (m)"
    )
    weather_code = models.IntegerField(
        null=True, blank=True, help_text="WMO weather interpretation code"
    )

    # ------------------------------------------------------------------ #
    # Source metadata                                                      #
    # ------------------------------------------------------------------ #
    source = models.CharField(
        max_length=32,
        default="open_meteo",
        help_text="Data provider identifier",
    )

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["latitude", "longitude", "observed_at"]),
            models.Index(fields=["observed_at"]),
            models.Index(fields=["city"]),
        ]
        verbose_name = "Weather Observation"
        verbose_name_plural = "Weather Observations"

    def __str__(self):
        label = self.city or f"({self.latitude:.2f}, {self.longitude:.2f})"
        return f"[Open-Meteo] {label} @ {self.observed_at.strftime('%Y-%m-%d %H:%M')} UTC"


class WeatherForecast(models.Model):
    """
    Hourly 72-hour weather forecast from Open-Meteo.

    Regenerated every hour. The forecast horizon covers the 24-72 h window
    required by the AQI Forecast model (Model 2).
    """

    # ------------------------------------------------------------------ #
    # Location                                                             #
    # ------------------------------------------------------------------ #
    latitude = models.FloatField()
    longitude = models.FloatField()
    city = models.CharField(max_length=128, blank=True)

    # ------------------------------------------------------------------ #
    # Timing                                                               #
    # ------------------------------------------------------------------ #
    forecast_generated_at = models.DateTimeField(
        default=timezone.now,
        help_text="UTC time this forecast batch was created",
    )
    valid_time = models.DateTimeField(
        help_text="UTC hour this forecast row is valid for"
    )
    lead_hours = models.PositiveSmallIntegerField(
        help_text="Hours ahead from forecast_generated_at (1-72)"
    )

    # ------------------------------------------------------------------ #
    # Forecast parameters                                                  #
    # ------------------------------------------------------------------ #
    temperature_2m = models.FloatField(null=True, blank=True, help_text="°C")
    relative_humidity_2m = models.FloatField(null=True, blank=True, help_text="%")
    precipitation = models.FloatField(null=True, blank=True, help_text="mm")
    precipitation_probability = models.FloatField(
        null=True, blank=True, help_text="Precipitation probability (%)"
    )
    wind_speed_10m = models.FloatField(
        null=True, blank=True, help_text="km/h — key input for AQI dispersion"
    )
    wind_direction_10m = models.FloatField(
        null=True, blank=True, help_text="Degrees — key input for AQI dispersion"
    )
    wind_gusts_10m = models.FloatField(null=True, blank=True, help_text="km/h")
    surface_pressure = models.FloatField(null=True, blank=True, help_text="hPa")
    cloud_cover = models.FloatField(null=True, blank=True, help_text="%")
    visibility = models.FloatField(null=True, blank=True, help_text="m")
    weather_code = models.IntegerField(null=True, blank=True)

    # Boundary-layer height is a strong proxy for mixing / dispersion
    boundary_layer_height = models.FloatField(
        null=True,
        blank=True,
        help_text="Planetary boundary layer height (m) — affects pollutant mixing",
    )

    source = models.CharField(max_length=32, default="open_meteo")

    class Meta:
        ordering = ["valid_time"]
        indexes = [
            models.Index(fields=["latitude", "longitude", "valid_time"]),
            models.Index(fields=["valid_time"]),
            models.Index(fields=["city", "valid_time"]),
            models.Index(fields=["forecast_generated_at"]),
        ]
        verbose_name = "Weather Forecast"
        verbose_name_plural = "Weather Forecasts"

    def __str__(self):
        label = self.city or f"({self.latitude:.2f}, {self.longitude:.2f})"
        return (
            f"[Open-Meteo Forecast +{self.lead_hours}h] "
            f"{label} valid {self.valid_time.strftime('%Y-%m-%d %H:%M')} UTC"
        )


class NASAPowerReanalysis(models.Model):
    """
    Historical meteorological reanalysis data from NASA POWER API.

    Used for:
      - Training the Calibration model (Model 1) — historical weather context
      - Back-filling gaps in Open-Meteo near-real-time data
      - Providing multi-year climate baselines for anomaly detection
    """

    # ------------------------------------------------------------------ #
    # Location                                                             #
    # ------------------------------------------------------------------ #
    latitude = models.FloatField()
    longitude = models.FloatField()
    city = models.CharField(max_length=128, blank=True)

    # ------------------------------------------------------------------ #
    # Date (daily reanalysis — NASA POWER daily resolution)               #
    # ------------------------------------------------------------------ #
    date = models.DateField(help_text="Date of this reanalysis record (UTC)")
    fetched_at = models.DateTimeField(default=timezone.now)

    # ------------------------------------------------------------------ #
    # NASA POWER parameters (MERRA-2 reanalysis)                          #
    # ------------------------------------------------------------------ #
    # Temperatures
    temperature_max = models.FloatField(
        null=True, blank=True, help_text="Daily max temperature at 2 m (°C)"
    )
    temperature_min = models.FloatField(
        null=True, blank=True, help_text="Daily min temperature at 2 m (°C)"
    )
    temperature_mean = models.FloatField(
        null=True, blank=True, help_text="Daily mean temperature at 2 m (°C)"
    )

    # Wind (key for pollutant dispersion modelling)
    wind_speed_10m_mean = models.FloatField(
        null=True, blank=True, help_text="Daily mean wind speed at 10 m (m/s)"
    )
    wind_direction_10m_mean = models.FloatField(
        null=True, blank=True,
        help_text="Daily mean wind direction at 10 m (degrees, meteorological)"
    )

    # Moisture
    specific_humidity = models.FloatField(
        null=True, blank=True, help_text="Daily mean specific humidity at 2 m (g/kg)"
    )
    relative_humidity = models.FloatField(
        null=True, blank=True, help_text="Daily mean relative humidity at 2 m (%)"
    )
    precipitation = models.FloatField(
        null=True, blank=True, help_text="Total daily precipitation (mm/day)"
    )

    # Radiation
    surface_shortwave_radiation = models.FloatField(
        null=True,
        blank=True,
        help_text="All-sky surface shortwave downward irradiance (W/m²)",
    )

    # Pressure
    surface_pressure = models.FloatField(
        null=True, blank=True, help_text="Daily mean surface pressure (kPa)"
    )

    # Boundary-layer
    boundary_layer_height = models.FloatField(
        null=True,
        blank=True,
        help_text="Daily mean planetary boundary layer height (m)",
    )

    source = models.CharField(max_length=32, default="nasa_power")

    class Meta:
        ordering = ["-date"]
        unique_together = [["latitude", "longitude", "date"]]
        indexes = [
            models.Index(fields=["latitude", "longitude", "date"]),
            models.Index(fields=["date"]),
            models.Index(fields=["city", "date"]),
        ]
        verbose_name = "NASA POWER Reanalysis"
        verbose_name_plural = "NASA POWER Reanalysis Records"

    def __str__(self):
        label = self.city or f"({self.latitude:.2f}, {self.longitude:.2f})"
        return f"[NASA POWER] {label} — {self.date}"
