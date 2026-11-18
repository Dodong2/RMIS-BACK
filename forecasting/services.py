import logging
import math
from datetime import date

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from budget_lib.models import LineItem
from financial_monitoring.models import Disbursement, ProcurementRequest

logger = logging.getLogger(__name__)

MIN_HISTORY_MONTHS = 6
MIN_HISTORY_FOR_BACKTEST = 12  # client Task 78-C: below 12 months the accuracy figures would be misleading
HOLDOUT_MONTHS = 3  # latest months, chronological (client: 3-6)
FORECAST_HORIZON_MONTHS = 3
ARIMA_ORDER = (1, 1, 1)
CONFIDENCE_LEVEL = 0.95


def monthly_disbursement_series(project):
    """Ordered [(month_start_date, total_amount), ...] across all of the
    project's disbursements, regardless of which budget version they're under.
    Every calendar month from the first to the last disbursement is included; a
    month with no disbursement is 0 (client Task 78-C), so the series is evenly spaced."""
    rows = (
        Disbursement.objects.filter(line_item__budget__project=project)
        .annotate(month=TruncMonth("disbursed_on"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    totals = {row["month"]: float(row["total"]) for row in rows}
    if not totals:
        return []
    series, month, last = [], min(totals), max(totals)
    while month <= last:
        series.append((month, totals.get(month, 0.0)))
        month = _next_month(month)
    return series


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


def accuracy_metrics(actual, predicted):
    """(MAE, RMSE, MAPE) for aligned month lists. MAPE skips months whose actual is 0 and is None when all are 0."""
    errors = [abs(a - p) for a, p in zip(actual, predicted)]
    mae = sum(errors) / len(errors)
    rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
    nonzero = [(a, e) for a, e in zip(actual, errors) if a != 0]
    mape = (sum(e / abs(a) for a, e in nonzero) / len(nonzero) * 100) if nonzero else None
    return mae, rmse, mape


def backtest(values):
    """Fit on all but the latest HOLDOUT_MONTHS (chronological, never shuffled), forecast those months and compare
    with what actually happened. Returns (mae, rmse, mape, backtest_status, backtest_note)."""
    if len(values) < MIN_HISTORY_FOR_BACKTEST:
        return None, None, None, "insufficient_history", (
            f"Not backtested: needs at least {MIN_HISTORY_FOR_BACKTEST} months of disbursement history, has {len(values)}."
        )
    train, holdout = values[:-HOLDOUT_MONTHS], values[-HOLDOUT_MONTHS:]
    try:
        predicted, _ = _fit_and_forecast(train, HOLDOUT_MONTHS)
        if len(predicted) != HOLDOUT_MONTHS or not all(math.isfinite(p) for p in predicted):
            raise ValueError("the model returned no usable predictions")
    except Exception as exc:
        logger.warning("Forecast backtest failed: %s", exc)
        return None, None, None, "failed", f"Backtest failed: {str(exc)[:240]}"
    mae, rmse, mape = accuracy_metrics(holdout, predicted)
    note = "" if mape is not None else f"MAPE unavailable: actual disbursement was ₱0 in all {HOLDOUT_MONTHS} holdout months."
    return mae, rmse, mape, "completed", note


def _budget_snapshot(project):
    current_budget = project.budgets.filter(is_current=True).first()
    if current_budget is None:
        return None, None
    approved = LineItem.objects.filter(budget=current_budget).aggregate(total=Sum("amount"))["total"]
    actual = (
        Disbursement.objects.filter(line_item__budget=current_budget).aggregate(total=Sum("amount"))["total"] or 0
    )
    return approved, actual


def unpaid_commitments(project):
    """Procurement requests of the current LIB that still reserve money: not cancelled and not paid (a paid request's
    Disbursement is already in the actual, so it is never counted twice). Same rule as uncommitted_balance."""
    return (
        ProcurementRequest.objects.filter(line_item__budget__project=project, line_item__budget__is_current=True)
        .exclude(status="cancelled")
        .filter(disbursement__isnull=True)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )


def run_forecast(project, run_by):
    from .models import ForecastRun, MonthlyForecast

    series = monthly_disbursement_series(project)
    months_of_history = len(series)
    values = [amount for _, amount in series]
    mae, rmse, mape, backtest_status, backtest_note = backtest(values)
    backtest_fields = {"backtest_status": backtest_status, "backtest_note": backtest_note}

    if months_of_history < MIN_HISTORY_MONTHS:
        return ForecastRun.objects.create(
            project=project,
            run_by=run_by,
            months_of_history=months_of_history,
            **backtest_fields,
            status="insufficient_data",
            error_message=f"Needs at least {MIN_HISTORY_MONTHS} months of disbursement history, has {months_of_history}.",
        )

    last_period = series[-1][0]

    try:
        mean, ci = _fit_and_forecast(values, FORECAST_HORIZON_MONTHS)
    except Exception as exc:
        return ForecastRun.objects.create(
            project=project,
            run_by=run_by,
            months_of_history=months_of_history,
            **backtest_fields,
            status="failed",
            error_message=str(exc)[:300],
        )

    approved, actual = _budget_snapshot(project)
    projected_total = float(actual or 0) + sum(mean)
    # Task 27 (2026-10-30, Carl Q5): the flag also counts unpaid commitments; projected_total stays actual + forecast.
    is_overrun_risk = approved is not None and projected_total + float(unpaid_commitments(project)) > float(approved)

    run = ForecastRun.objects.create(
        project=project,
        run_by=run_by,
        months_of_history=months_of_history,
        arima_order=str(ARIMA_ORDER),
        **backtest_fields,
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
