from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from .models import Document
from .serializers import MANAGE_ROLES, DocumentListSerializer, DocumentSerializer


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
        if self.request.query_params.get("current_only") == "true":
            qs = qs.filter(is_current=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class DocumentDetailView(generics.RetrieveAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]


class DocumentArchiveView(APIView):
    permission_classes = [HasRole(MANAGE_ROLES)]

    def post(self, request, pk):
        document = generics.get_object_or_404(Document, pk=pk)
        if document.is_archived:
            return Response({"detail": "This document is already archived."}, status=status.HTTP_400_BAD_REQUEST)
        document.is_archived = True
        document.save(update_fields=["is_archived"])
        return Response(DocumentSerializer(document, context={"request": request}).data)
