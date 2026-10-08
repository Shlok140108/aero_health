import os
import pickle
import django
import pandas as pd
from datetime import datetime
from django.conf import settings
from geopy.distance import geodesic

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

settings.configure()
MODELPATH = os.path.join(settings.BASE_DIR , "models" , "aqi_xgboost.pkl")

_model = None



MODELS_DIR = os.path.join(settings.BASE_DIR, "models")
PROPHET_DIR = os.path.join(MODELS_DIR, "prophet_cities")

_xgb_temp_model = None
_city_lookup = None
_prophet_cache = {}  # loaded on demand, cached after first use

NEAR_CITY_THRESHOLD_KM = 30  # if within this distance of a known city, use Prophet instead of XGBoost


def get_xgb_temp_model():
    global _xgb_temp_model
    if _xgb_temp_model is None:
        with open(os.path.join(MODELS_DIR, "temp_xgboost.pkl"), "rb") as f:
            _xgb_temp_model = pickle.load(f)
    return _xgb_temp_model


def get_city_lookup():
    global _city_lookup
    if _city_lookup is None:
        with open(os.path.join(PROPHET_DIR, "city_lookup.pkl"), "rb") as f:
            _city_lookup = pickle.load(f)
    return _city_lookup


def get_prophet_model(city_name):
    if city_name not in _prophet_cache:
        path = os.path.join(PROPHET_DIR, f"{city_name}.pkl")
        with open(path, "rb") as f:
            _prophet_cache[city_name] = pickle.load(f)
    return _prophet_cache[city_name]


def find_nearby_city(lat, lon):
    """Returns the closest known city if within threshold distance, else None."""
    lookup = get_city_lookup()
    closest_city, closest_dist = None, float("inf")

    for city, coords in lookup.items():
        dist = geodesic((lat, lon), (coords["lat"], coords["lon"])).km
        if dist < closest_dist:
            closest_city, closest_dist = city, dist

    if closest_dist <= NEAR_CITY_THRESHOLD_KM:
        return closest_city
    return None


def predict_temperature(lat, lon, date=None):
    """
    Hybrid prediction:
    - If near one of the 10 known cities, use that city's Prophet model (more accurate).
    - Otherwise, fall back to the national XGBoost model (generalizes anywhere in India).
    Returns (predicted_temp, source) where source is "prophet" or "xgboost".
    """
    if date is None:
        date = datetime.now()

    nearby_city = find_nearby_city(lat, lon)

    if nearby_city:
        model = get_prophet_model(nearby_city)
        future = pd.DataFrame({"ds": [pd.Timestamp(date)]})
        forecast = model.predict(future)
        predicted_temp = float(forecast["yhat"].iloc[0])
        return predicted_temp, "prophet", nearby_city

    else:
        model = get_xgb_temp_model()
        features = pd.DataFrame([{
            "lat": lat, "lon": lon,
            "month": date.month, "day_of_year": date.timetuple().tm_yday,
        }])
        predicted_temp = float(model.predict(features)[0])
        return predicted_temp, "xgboost", None


def get_model():
    global _model
    if _model is None:
        with open(MODELPATH , "rb") as f:
            _model = pickle.load(f)
    return _model

def predict_aqi(
    pm25, pm10, no, no2, nox, nh3, co, so2, o3,
    benzene, toluene, lat, lon, month, day_of_week, date=None
):
    if date is None:
        date = datetime.now()
    features = pd.DataFrame([{
        "PM2.5": pm25,
        "PM10": pm10,
        "NO": no,
        "NO2": no2,
        "NOx": nox,
        "NH3": nh3,
        "CO": co,
        "SO2": so2,
        "O3": o3,
        "Benzene": benzene,
        "Toluene": toluene,
        "lat": lat,
        "lon": lon,
        "month": month,
        "Day_of_week": day_of_week,
    }])

    model = get_model()
    prediction = model.predict(features)
    return prediction