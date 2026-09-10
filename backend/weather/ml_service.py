import os
import pickle
import django
import pandas as pd
from datetime import datetime
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

settings.configure()
MODELPATH = os.path.join(settings.BASE_DIR , "models" , "aqi_xgboost.pkl")

_model = None

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