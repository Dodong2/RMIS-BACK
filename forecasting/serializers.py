from rest_framework import serializers

from .models import ForecastRun, MonthlyForecast

FORECAST_ROLES = ["system_admin", "drd", "vprei", "finance_budget"]


class MonthlyForecastSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthlyForecast
        fields = ["id", "period", "predicted_amount", "lower_bound", "upper_bound"]


class ForecastRunSerializer(serializers.ModelSerializer):
    forecasts = MonthlyForecastSerializer(many=True, read_only=True)

    class Meta:
        model = ForecastRun
        fields = [
            "id", "project", "run_by", "run_at", "months_of_history", "arima_order",
            "status", "error_message", "mae", "rmse", "mape",
            "approved_budget_total", "actual_to_date", "projected_total_at_horizon",
            "is_overrun_risk", "forecasts",
        ]
        read_only_fields = [f for f in fields if f != "project"]
