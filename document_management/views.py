from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole, acting_for, role_can, visible_documents
from .models import Document, DocumentShare
from .serializers import DocumentListSerializer, DocumentSerializer, DocumentShareSerializer


class DocumentListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return DocumentSerializer if self.request.method == "POST" else DocumentListSerializer

    def get_queryset(self):
        qs = Document.objects.all().order_by("-uploaded_at")
        for param in ("project", "study", "document_type", "stage"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{param: value})
        if self.request.query_params.get("review_status"):
            qs = qs.filter(review_status=self.request.query_params["review_status"])
        if self.request.query_params.get("current_only") == "true":
            qs = qs.filter(is_current=True)
        return visible_documents(self.request.user, qs)

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class DocumentDetailView(generics.RetrieveAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return visible_documents(self.request.user, Document.objects.all())


class DocumentArchiveView(APIView):
    permission_classes = [HasRole("documents.manage")]

    def post(self, request, pk):
        document = generics.get_object_or_404(Document, pk=pk)
        if document.is_archived:
            return Response({"detail": "This document is already archived."}, status=status.HTTP_400_BAD_REQUEST)
        document.is_archived = True
        document.save(update_fields=["is_archived"])
        return Response(DocumentSerializer(document, context={"request": request}).data)


class DocumentReviewView(APIView):
    """POST {"review_status": "approved" | "returned", "review_remarks": ...}."""

    permission_classes = [HasRole("documents.manage")]

    def post(self, request, pk):
        document = generics.get_object_or_404(visible_documents(request.user, Document.objects.all()), pk=pk)
        review_status = request.data.get("review_status")
        if review_status not in ("approved", "returned"):
            return Response({"review_status": "must be 'approved' or 'returned'."}, status=status.HTTP_400_BAD_REQUEST)
        document.review_status = review_status
        document.review_remarks = request.data.get("review_remarks", "")
        document.reviewed_by, document.reviewed_at = request.user, timezone.now()
        document.save(update_fields=["review_status", "review_remarks", "reviewed_by", "reviewed_at"])
        return Response(DocumentListSerializer(document).data)


def can_share(user, document):
    """Q8: the document's project leader (or program leader, or their acting replacement) or a documents.manage
    holder may grant/revoke shares, and only for a document they can see themselves."""
    if not visible_documents(user, Document.objects.filter(pk=document.pk)).exists():
        return False
    if role_can(user, "documents.manage"):
        return True
    leads = {user.pk, *acting_for(user)}
    program = document.project.program
    return document.project.lead_id in leads or (program is not None and program.lead_id in leads)


class DocumentShareListCreateView(generics.ListCreateAPIView):
    """GET/POST documents/<pk>/shares/ — who this document is shared with, and granting a new share."""

    serializer_class = DocumentShareSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_document(self):
        document = generics.get_object_or_404(Document, pk=self.kwargs["pk"])
        if not can_share(self.request.user, document):
            self.permission_denied(self.request, message="Only the project leader or RIUH can share this document.")
        return document

    def get_queryset(self):
        return DocumentShare.objects.filter(document=self.get_document()).select_related("user__role", "granted_by").order_by("-granted_at")

    def perform_create(self, serializer):
        serializer.save(document=self.get_document(), granted_by=self.request.user)


class DocumentShareRevokeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        share = generics.get_object_or_404(DocumentShare, pk=pk)
        if not can_share(request.user, share.document):
            self.permission_denied(request, message="Only the project leader or RIUH can revoke this share.")
        if share.revoked_at:
            return Response({"detail": "This share is already revoked."}, status=status.HTTP_400_BAD_REQUEST)
        share.revoked_at = timezone.now()
        share.revoked_by = request.user
        share.save(update_fields=["revoked_at", "revoked_by"])
        return Response(DocumentShareSerializer(share).data)
