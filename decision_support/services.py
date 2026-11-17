from django.db.models import Sum

from budget_lib.models import LineItem
from compliance.models import EthicsReviewReference
from financial_monitoring.models import Disbursement
from forecasting.models import ForecastRun
from monitoring.serializers import compute_escalation_status, compute_renewal_eligible
from outputs.models import CreativeWorkRecord, IPRecord, PublicationRecord
from risk_indicators.services import compute_project_risk

from . import formula

# Saaty's Random Index (RI) table for consistency-ratio normalization, n=1..10.
SAATY_RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def compute_ahp_weights(criteria_ids, comparisons):
    """Eigenvector-approximation AHP: normalize the pairwise matrix's columns,
    average each row to get the priority vector, then derive lambda_max/CI/CR
    from that same matrix and vector.

    comparisons: {(row_id, col_id): value} for row_id < col_id pairs only
    (Saaty scale); the reciprocal (col, row) = 1/value is filled in here.
    Returns ({criterion_id: weight}, consistency_ratio).
    """
    n = len(criteria_ids)
    if n == 0:
        return {}, 0.0
    if n == 1:
        return {criteria_ids[0]: 1.0}, 0.0

    index = {cid: i for i, cid in enumerate(criteria_ids)}
    matrix = [[1.0] * n for _ in range(n)]
    for (a, b), value in comparisons.items():
        i, j = index[a], index[b]
        matrix[i][j] = value
        matrix[j][i] = 1.0 / value

    col_sums = [sum(matrix[i][j] for i in range(n)) for j in range(n)]
    normalized = [[matrix[i][j] / col_sums[j] for j in range(n)] for i in range(n)]
    weights_list = [sum(row) / n for row in normalized]

    weighted_sum = [sum(matrix[i][j] * weights_list[j] for j in range(n)) for i in range(n)]
    lambda_max = sum(weighted_sum[i] / weights_list[i] for i in range(n)) / n

    ci = (lambda_max - n) / (n - 1)
    ri = SAATY_RANDOM_INDEX.get(n, 1.49)
    cr = (ci / ri) if ri else 0.0

    weights = {cid: weights_list[index[cid]] for cid in criteria_ids}
    return weights, round(cr, 4)


def _output_score(project):
    return (
        PublicationRecord.objects.filter(project=project).count()
        + IPRecord.objects.filter(project=project).count()
        + CreativeWorkRecord.objects.filter(project=project).count()
    )


def _compliance_score(project):
    reviews = EthicsReviewReference.objects.filter(project=project)
    total = reviews.count()
    if total == 0:
        return 0.5  # neutral — nothing to assess yet, not penalized
    cleared = reviews.filter(status="approved").count()
    return cleared / total


def _budget_utilization_pct(project):
    current_budget = project.budgets.filter(is_current=True).first()
    if current_budget is None:
        return 0.0
    approved = LineItem.objects.filter(budget=current_budget).aggregate(total=Sum("amount"))["total"]
    if not approved:
        return 0.0
    actual = Disbursement.objects.filter(line_item__budget=current_budget).aggregate(total=Sum("amount"))["total"] or 0
    return float(actual) / float(approved) * 100


_ESCALATION_HEALTH = {"on_track": 1.0, "notify_dean_riuh": 0.5, "terminate_recommended": 0.0, "unknown": 0.5}


def _monitoring_health(project):
    return _ESCALATION_HEALTH[compute_escalation_status(project)["status"]]


def _renewal_eligible(project):
    return 1.0 if compute_renewal_eligible(project, has_justification=True) else 0.0


def _overrun_risk_inverse(project):
    latest = ForecastRun.objects.filter(project=project, status="success").order_by("-run_at").first()
    if latest is None:
        return 0.5  # neutral — no forecast run yet
    return 0.0 if latest.is_overrun_risk else 1.0


def _risk_score_inverse(project):
    return 25 - compute_project_risk(project)["risk_score"]  # 25 = max on the 5x5 scale


# Every metric here is defined so a HIGHER raw value is always better.
CRITERIA_METRICS = {
    "output_score": _output_score,
    "compliance_score": _compliance_score,
    "budget_utilization_pct": _budget_utilization_pct,
    "monitoring_health": _monitoring_health,
    "renewal_eligible": _renewal_eligible,
    "overrun_risk_inverse": _overrun_risk_inverse,
    "risk_score_inverse": _risk_score_inverse,
}

# Task 76 (Figma DSS): each standard metric is put on an absolute 0-100 scale, so a project's score no longer
# depends on who else is in the run (the old min-max scaling gave every tied project 100).
_TO_100 = {
    "compliance_score": lambda v: v * 100,
    "budget_utilization_pct": lambda v: v,
    "monitoring_health": lambda v: v * 100,
    "renewal_eligible": lambda v: v * 100,
    "overrun_risk_inverse": lambda v: v * 100,
    "risk_score_inverse": lambda v: v * 4,  # 25 = best on the 5x5 scale
}


def _clamp(v):
    return max(0.0, min(100.0, float(v)))


def standard_scores(metric_key, raw_by_project):
    """{project_id: 0-100}. Output volume is a count with no upper bound, so it is scored against the highest
    count in the run (0 when nobody has outputs); every other metric already has a fixed range."""
    if metric_key == "output_score":
        top = max(raw_by_project.values(), default=0)
        return {pid: (_clamp(v / top * 100) if top else 0.0) for pid, v in raw_by_project.items()}
    return {pid: _clamp(_TO_100[metric_key](v)) for pid, v in raw_by_project.items()}


def formula_snapshot(criterion):
    if criterion.formula_mode == "custom":
        return {"metric_key": criterion.metric_key, "mode": "custom", "formula": criterion.custom_formula}
    return {"metric_key": criterion.metric_key, "mode": "standard"}


def custom_scores(criterion, projects, own_raw, standard):
    """{project_id: 0-100} from the indicator's custom formula. `score` is its standard score; any other variable is
    that metric's raw value, computed only when the formula uses it."""
    used = formula.validate(criterion.custom_formula)
    extra = {key: {p.id: CRITERIA_METRICS[key](p) for p in projects} for key in used - {"score", criterion.metric_key}}
    result = {}
    for p in projects:
        values = {"score": standard[p.id], criterion.metric_key: own_raw[p.id]}
        values.update({key: by_project[p.id] for key, by_project in extra.items()})
        result[p.id] = formula.evaluate(criterion.custom_formula, values)
    return result


def run_wsm(ahp_run, projects, created_by, label, funding_type_filter="", campus_filter=""):
    from .models import FundingRecommendationRun, ProjectScore

    criteria = list(ahp_run.criteria.filter(is_active=True))
    weights = {str(c.id): float(ahp_run.weights.get(str(c.id), 0)) for c in criteria}

    raw_by_criterion = {c.id: {p.id: CRITERIA_METRICS[c.metric_key](p) for p in projects} for c in criteria}
    score_by_criterion = {c.id: standard_scores(c.metric_key, raw_by_criterion[c.id]) for c in criteria}
    for c in criteria:
        if c.formula_mode == "custom":
            score_by_criterion[c.id] = custom_scores(c, projects, raw_by_criterion[c.id], score_by_criterion[c.id])

    run = FundingRecommendationRun.objects.create(
        ahp_run=ahp_run,
        label=label,
        created_by=created_by,
        funding_type_filter=funding_type_filter,
        campus_filter=campus_filter,
        method=FundingRecommendationRun.METHOD_ABSOLUTE,
        weights_snapshot=weights,
        formulas_snapshot={str(c.id): formula_snapshot(c) for c in criteria},
    )

    composite_by_project = {}
    for p in projects:
        raw = {c.id: raw_by_criterion[c.id][p.id] for c in criteria}
        # Stored as 0-1 (score / 100) so normalized_scores keeps its old shape for the pages that read it.
        normalized = {c.id: score_by_criterion[c.id][p.id] / 100 for c in criteria}
        composite = sum(normalized[c.id] * weights[str(c.id)] for c in criteria)
        composite_by_project[p.id] = (raw, normalized, composite)

    ranked = sorted(projects, key=lambda p: composite_by_project[p.id][2], reverse=True)
    for rank, p in enumerate(ranked, start=1):
        raw, normalized, composite = composite_by_project[p.id]
        ProjectScore.objects.create(
            run=run,
            project=p,
            raw_scores={str(k): v for k, v in raw.items()},
            normalized_scores={str(k): v for k, v in normalized.items()},
            composite_score=round(composite, 6),
            rank=rank,
        )
    return run


def sensitivity_analysis(run, criterion_id, delta):
    """Live-computed, not persisted: bump one criterion's weight by `delta`,
    proportionally shrink the rest so weights still sum to 1, and report how
    the ranking would change. Reuses this run's already-stored normalized
    scores rather than re-querying project data."""
    scores = list(run.scores.all())
    weights = {int(k): float(v) for k, v in (run.weights_snapshot or run.ahp_run.weights).items()}

    if criterion_id not in weights:
        raise ValueError("criterion is not part of this run's AHP weighting")

    old_weight = weights[criterion_id]
    new_weight = max(0.0, min(1.0, old_weight + delta))
    remaining_old = 1.0 - old_weight
    remaining_new = 1.0 - new_weight
    adjusted = {}
    for cid, w in weights.items():
        if cid == criterion_id:
            adjusted[cid] = new_weight
        elif remaining_old > 0:
            adjusted[cid] = w / remaining_old * remaining_new
        else:
            adjusted[cid] = 0.0

    results = []
    for score in scores:
        composite = sum(score.normalized_scores.get(str(cid), 0) * w for cid, w in adjusted.items())
        results.append(
            {
                "project": score.project_id,
                "original_composite": score.composite_score,
                "original_rank": score.rank,
                "adjusted_composite": round(composite, 6),
            }
        )

    results.sort(key=lambda r: r["adjusted_composite"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["adjusted_rank"] = i
        r["rank_change"] = r["original_rank"] - i  # positive = moved up under the new weighting

    return {
        "criterion_id": criterion_id,
        "old_weight": old_weight,
        "new_weight": new_weight,
        "adjusted_weights": {str(k): v for k, v in adjusted.items()},
        "results": results,
    }
