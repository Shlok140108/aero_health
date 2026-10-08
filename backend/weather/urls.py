from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("predict-temperature/", views.predict_temperature_view, name="predict-temperature"),
]