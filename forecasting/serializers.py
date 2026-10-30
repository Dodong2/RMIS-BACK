from rest_framework import serializers

from .models import ForecastRun, MonthlyForecast
from .services import unpaid_commitments

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
FORECAST_ROLES = ["system_admin", "vprei", "finance_budget", "project_leader"]


class MonthlyForecastSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthlyForecast
        fields = ["id", "period", "predicted_amount", "lower_bound", "upper_bound"]


class ForecastRunSerializer(serializers.ModelSerializer):
    forecasts = MonthlyForecastSerializer(many=True, read_only=True)
    unpaid_commitments = serializers.SerializerMethodField()

    class Meta:
        model = ForecastRun
        fields = [
            "id", "project", "run_by", "run_at", "months_of_history", "arima_order",
            "status", "error_message", "mae", "rmse", "mape",
            "approved_budget_total", "actual_to_date", "projected_total_at_horizon",
            "is_overrun_risk", "unpaid_commitments", "forecasts",
        ]
        read_only_fields = [f for f in fields if f != "project"]

    def get_unpaid_commitments(self, run):
        # shortcut: today's figure, not frozen at run_at; add a model field if run history must keep its own.
        return str(unpaid_commitments(run.project))
