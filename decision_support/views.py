from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole, role_can
from config.concurrency import lock
from research_projects.models import Project

from . import services
from .models import AHPMatrixRun, AHPPairwiseComparison, DecisionCriterion, DecisionRecord, FundingRecommendationRun
from .serializers import (
    AHPMatrixRunSerializer,
    AHPPairwiseComparisonSerializer,
    CriterionFormulaSerializer,
    DecisionCriterionSerializer,
    DecisionRecordSerializer,
    FundingRecommendationRunSerializer,
)


class RoleWritesMixin:
    write_permission = "dss.manage"

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [HasRole("dss.view")]  # client Task 76: the DSS is for system_admin, vprei, university_admin, crc_chair
        return [HasRole(self.write_permission)]


class DecisionCriterionListCreateView(RoleWritesMixin, generics.ListCreateAPIView):
    queryset = DecisionCriterion.objects.all()
    serializer_class = DecisionCriterionSerializer


class DecisionCriterionDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = DecisionCriterion.objects.all()
    serializer_class = DecisionCriterionSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def partial_update(self, request, *args, **kwargs):
        criterion = self.get_object()
        serializer = CriterionFormulaSerializer(criterion, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(DecisionCriterionSerializer(criterion).data)


class AHPMatrixRunListCreateView(RoleWritesMixin, generics.ListCreateAPIView):
    queryset = AHPMatrixRun.objects.all()
    serializer_class = AHPMatrixRunSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AHPMatrixRunDetailView(RoleWritesMixin, generics.RetrieveAPIView):
    queryset = AHPMatrixRun.objects.all()
    serializer_class = AHPMatrixRunSerializer


class AHPComparisonSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not role_can(request.user, "dss.manage"):
            return Response(
                {"detail": "Only DRD/VPREI/system_admin may submit AHP comparisons."}, status=status.HTTP_403_FORBIDDEN
            )
        with transaction.atomic():
            # Locked so comparisons can't be written into a run that is being finalized at the same moment.
            run = lock(AHPMatrixRun.objects.all(), pk=pk)
            if run.status == "finalized":
                return Response({"detail": "This AHP run is already finalized."}, status=status.HTTP_400_BAD_REQUEST)

            criteria_ids = set(run.criteria.values_list("id", flat=True))
            pairs = []
            for item in request.data.get("comparisons", []):
                row_id, col_id, value = item["criterion_row"], item["criterion_col"], float(item["value"])
                if row_id not in criteria_ids or col_id not in criteria_ids:
                    return Response(  # checked before any write, so a bad pair saves nothing
                        {"detail": f"Criteria {row_id}/{col_id} are not part of this run."}, status=status.HTTP_400_BAD_REQUEST
                    )
                if row_id == col_id:
                    continue
                if row_id > col_id:
                    row_id, col_id, value = col_id, row_id, 1.0 / value
                pairs.append((row_id, col_id, value))
            created = [
                AHPPairwiseComparison.objects.update_or_create(
                    run=run, criterion_row_id=row_id, criterion_col_id=col_id, defaults={"value": value}
                )[0]
                for row_id, col_id, value in pairs
            ]
        return Response(AHPPairwiseComparisonSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class AHPMatrixRunFinalizeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "compute"

    def post(self, request, pk):
        if not role_can(request.user, "dss.manage"):
            return Response(
                {"detail": "Only DRD/VPREI/system_admin may finalize an AHP run."}, status=status.HTTP_403_FORBIDDEN
            )
        with transaction.atomic():
            return self._finalize(lock(AHPMatrixRun.objects.all(), pk=pk))

    def _finalize(self, run):
        # Finalized weights are cited by recommendation runs, so they are computed once and never overwritten.
        if run.status != "draft":
            return Response({"detail": "This AHP run is already finalized."}, status=status.HTTP_400_BAD_REQUEST)
        criteria_ids = list(run.criteria.values_list("id", flat=True))
        n = len(criteria_ids)
        expected_pairs = n * (n - 1) // 2
        comparisons = {(c.criterion_row_id, c.criterion_col_id): c.value for c in run.comparisons.all()}
        if len(comparisons) < expected_pairs:
            return Response(
                {"detail": f"Need {expected_pairs} pairwise comparisons, have {len(comparisons)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        weights, cr = services.compute_ahp_weights(criteria_ids, comparisons)
        run.weights = {str(k): v for k, v in weights.items()}
        run.consistency_ratio = cr
        run.is_consistent = cr <= 0.10
        run.status = "finalized"
        run.save()
        return Response(AHPMatrixRunSerializer(run).data)


MANUAL_WEIGHT_MIN, MANUAL_WEIGHT_MAX = 1, 60  # Figma Assign Weights — DSS-02 sliders


def manual_weight_errors(weights, criteria_ids):
    """weights = {criterion_id: whole percent}. Returns an error message, or None when valid."""
    if not isinstance(weights, dict):
        return "weights must be an object of {indicator id: percent}."
    try:
        given = {int(k): v for k, v in weights.items()}
    except (TypeError, ValueError):
        return "weights keys must be indicator ids."
    if set(given) != set(criteria_ids):
        return "Give a weight for every indicator in this model, and only those."
    if any(type(v) is not int for v in given.values()):
        return "Weights must be whole percents."
    low, high = (100, 100) if len(criteria_ids) == 1 else (MANUAL_WEIGHT_MIN, MANUAL_WEIGHT_MAX)
    if any(not low <= v <= high for v in given.values()):
        return f"Each weight must be from {low}% to {high}%."
    total = sum(given.values())
    if total != 100:
        return f"Weights must add up to 100% (now {total}%)."
    return None


class AHPMatrixRunWeightsView(APIView):
    """POST {"weights": {criterion_id: percent}}: Edit Weights — DSS-02. Replaces the model's weights (it becomes
    ready to run); recommendation runs made earlier keep their own weights_snapshot."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not role_can(request.user, "dss.manage"):
            return Response({"detail": "You can't edit DSS weights."}, status=status.HTTP_403_FORBIDDEN)
        with transaction.atomic():
            run = lock(AHPMatrixRun.objects.all(), pk=pk)
            weights = request.data.get("weights")
            error = manual_weight_errors(weights, list(run.criteria.values_list("id", flat=True)))
            if error:
                return Response({"weights": [error]}, status=status.HTTP_400_BAD_REQUEST)
            run.weights = {str(int(k)): v / 100 for k, v in weights.items()}
            run.weight_source = "manual"
            run.status = "finalized"
            run.consistency_ratio = None
            run.is_consistent = None
            run.save(update_fields=["weights", "weight_source", "status", "consistency_ratio", "is_consistent"])
        return Response(AHPMatrixRunSerializer(run).data)


class FundingRecommendationRunTriggerView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "compute"

    def post(self, request):
        if not role_can(request.user, "dss.manage"):
            return Response(
                {"detail": "Only DRD/VPREI/system_admin may run a funding recommendation."}, status=status.HTTP_403_FORBIDDEN
            )

        ahp_run = get_object_or_404(AHPMatrixRun, pk=request.data.get("ahp_run"))
        ready = ahp_run.status == "finalized" and (ahp_run.weight_source == "manual" or ahp_run.is_consistent)
        if not ready:
            return Response(
                {"detail": "Set this model's weights first (Edit Weights, or AHP with a Consistency Ratio <= 0.10)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project_ids = request.data.get("project_ids")
        funding_type_filter = request.data.get("funding_type", "")
        campus_filter = request.data.get("campus", "")
        projects = Project.objects.all()
        if project_ids:
            projects = projects.filter(id__in=project_ids)
        if funding_type_filter:
            projects = projects.filter(funding_type=funding_type_filter)
        if campus_filter:
            projects = projects.filter(campus=campus_filter)
        projects = list(projects)
        if len(projects) < 2:
            return Response({"detail": "Need at least 2 candidate projects to rank."}, status=status.HTTP_400_BAD_REQUEST)

        run = services.run_wsm(
            ahp_run,
            projects,
            request.user,
            label=request.data.get("label", f"Recommendation run - {ahp_run.label}"),
            funding_type_filter=funding_type_filter,
            campus_filter=campus_filter,
        )
        return Response(FundingRecommendationRunSerializer(run).data, status=status.HTTP_201_CREATED)


class FundingRecommendationRunListView(generics.ListAPIView):
    queryset = FundingRecommendationRun.objects.all()
    serializer_class = FundingRecommendationRunSerializer
    permission_classes = [HasRole("dss.view")]


class FundingRecommendationRunDetailView(generics.RetrieveAPIView):
    queryset = FundingRecommendationRun.objects.all()
    serializer_class = FundingRecommendationRunSerializer
    permission_classes = [HasRole("dss.view")]


class SensitivityAnalysisView(APIView):
    permission_classes = [HasRole("dss.view")]
    throttle_scope = "compute"

    def get(self, request, pk):
        run = get_object_or_404(FundingRecommendationRun, pk=pk)
        try:
            criterion_id = int(request.query_params.get("criterion"))
            delta = float(request.query_params.get("delta", 0.1))
        except (TypeError, ValueError):
            return Response(
                {"detail": "criterion (id) and delta (float) query params required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            result = services.sensitivity_analysis(run, criterion_id, delta)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class DecisionRecordView(RoleWritesMixin, generics.ListCreateAPIView):
    """GET decisions on a recommendation run; POST {project, decision, indicative_amount?, rationale, reference_number}
    records (or replaces) the decision for one ranked project."""

    write_permission = "dss.decide"
    serializer_class = DecisionRecordSerializer

    def get_run(self):
        return get_object_or_404(FundingRecommendationRun, pk=self.kwargs["pk"])

    def get_queryset(self):
        return self.get_run().decisions.select_related("project").order_by("project_id")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "run": self.get_run()}

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record, _ = DecisionRecord.objects.update_or_create(
            run=self.get_run(), project=data.pop("project"), defaults={**data, "decided_by": request.user},
        )
        return Response(DecisionRecordSerializer(record).data, status=status.HTTP_201_CREATED)
