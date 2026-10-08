from rest_framework.decorators import api_view
from rest_framework.response import Response
from .ml_service import predict_temperature


@api_view(["POST"])
def predict_temperature_view(request):
    """
    POST /api/weather/predict-temperature/
    Body: {lat, lon, date (optional, ISO format)}
    """
    lat = request.data.get("lat")
    lon = request.data.get("lon")
    date_str = request.data.get("date")

    date = None
    if date_str:
        from datetime import datetime
        date = datetime.fromisoformat(date_str)

    predicted_temp, source, city = predict_temperature(lat, lon, date)

    return Response({
        "predicted_temperature": round(predicted_temp, 1),
        "model_used": source,           # "prophet" or "xgboost" — good for your validation/transparency feature
        "matched_city": city,            # which known city it matched, if any
    })