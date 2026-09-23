from datetime import date

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement

MIN_HISTORY_MONTHS = 6
MIN_HISTORY_FOR_HOLDOUT = 9
HOLDOUT_MONTHS = 3
FORECAST_HORIZON_MONTHS = 3
ARIMA_ORDER = (1, 1, 1)
CONFIDENCE_LEVEL = 0.95


def monthly_disbursement_series(project):
    """Ordered [(month_start_date, total_amount), ...] across all of the
    project's disbursements, regardless of which budget version they're under."""
    rows = (
        Disbursement.objects.filter(line_item__budget__project=project)
        .annotate(month=TruncMonth("disbursed_on"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    return [(row["month"], float(row["total"])) for row in rows]


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _fit_and_forecast(train_values, steps):
    import numpy as np
    from statsmodels.tsa.arima.model import ARIMA

    fit = ARIMA(train_values, order=ARIMA_ORDER).fit()
    result = fit.get_forecast(steps=steps)
    mean = np.asarray(result.predicted_mean).reshape(-1).tolist()
    ci = np.asarray(result.conf_int(alpha=1 - CONFIDENCE_LEVEL)).tolist()
    return mean, ci


def _backtest_accuracy(values):
    """Fit on all but the last HOLDOUT_MONTHS, forecast that gap, compare to
    what actually happened. Best-effort — returns (None, None, None) if the
    fit fails or there isn't enough history to hold months out."""
    if len(values) < MIN_HISTORY_FOR_HOLDOUT:
        return None, None, None
    train, holdout = values[:-HOLDOUT_MONTHS], values[-HOLDOUT_MONTHS:]
    try:
        predicted, _ = _fit_and_forecast(train, HOLDOUT_MONTHS)
    except Exception:
        return None, None, None

    errors = [abs(actual - pred) for actual, pred in zip(holdout, predicted)]
    mae = sum(errors) / len(errors)
    rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
    nonzero = [(actual, e) for actual, e in zip(holdout, errors) if actual != 0]
    mape = (sum(e / actual for actual, e in nonzero) / len(nonzero) * 100) if nonzero else None
    return mae, rmse, mape


def _budget_snapshot(project):
    current_budget = project.budgets.filter(is_current=True).first()
    if current_budget is None:
        return None, None
    approved = LineItem.objects.filter(budget=current_budget).aggregate(total=Sum("amount"))["total"]
    actual = (
        Disbursement.objects.filter(line_item__budget=current_budget).aggregate(total=Sum("amount"))["total"] or 0
    )
    return approved, actual


def run_forecast(project, run_by):
    from .models import ForecastRun, MonthlyForecast

    series = monthly_disbursement_series(project)
    months_of_history = len(series)

    if months_of_history < MIN_HISTORY_MONTHS:
        return ForecastRun.objects.create(
            project=project,
            run_by=run_by,
            months_of_history=months_of_history,
            status="insufficient_data",
            error_message=f"Needs at least {MIN_HISTORY_MONTHS} months of disbursement history, has {months_of_history}.",
        )

    values = [amount for _, amount in series]
    last_period = series[-1][0]
    mae, rmse, mape = _backtest_accuracy(values)

    try:
        mean, ci = _fit_and_forecast(values, FORECAST_HORIZON_MONTHS)
    except Exception as exc:
        return ForecastRun.objects.create(
            project=project,
            run_by=run_by,
            months_of_history=months_of_history,
            status="failed",
            error_message=str(exc)[:300],
        )

    approved, actual = _budget_snapshot(project)
    projected_total = float(actual or 0) + sum(mean)
    is_overrun_risk = approved is not None and projected_total > float(approved)

    run = ForecastRun.objects.create(
        project=project,
        run_by=run_by,
        months_of_history=months_of_history,
        arima_order=str(ARIMA_ORDER),
        status="success",
        mae=round(mae, 2) if mae is not None else None,
        rmse=round(rmse, 2) if rmse is not None else None,
        mape=round(mape, 2) if mape is not None else None,
        approved_budget_total=approved,
        actual_to_date=actual,
        projected_total_at_horizon=round(projected_total, 2),
        is_overrun_risk=is_overrun_risk,
    )

    period = last_period
    for predicted, (lower, upper) in zip(mean, ci):
        period = _next_month(period)
        MonthlyForecast.objects.create(
            forecast_run=run,
            period=period,
            predicted_amount=round(predicted, 2),
            lower_bound=round(max(lower, 0), 2),
            upper_bound=round(upper, 2),
        )
    return run
