from datetime import date, timedelta

from accounts.testing import RMISTestCase
from document_management.models import Document, DocumentShare
from research_projects.models import Project


class DocumentSharingTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.riuh = self.make_user("riuh")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        self.document = Document.objects.create(
            project=project, document_type="other", sensitivity="financial", version_number=1,
            storage_path="p/f.pdf", file_name="f.pdf", file_size=1, uploaded_by=self.leader,
        )

    def share(self, granter, days=10):
        return self.client_for(granter).post(
            f"/api/documents/documents/{self.document.id}/shares/",
            {"user": self.riuh.id, "expires_on": str(date.today() + timedelta(days=days))}, format="json",
        )

    def riuh_can_open(self):
        return self.client_for(self.riuh).get(f"/api/documents/documents/{self.document.id}/").status_code == 200

    def test_riuh_cannot_open_a_financial_document_by_default(self):
        self.assertFalse(self.riuh_can_open())

    def test_project_leader_can_share_and_the_user_can_then_open_it(self):
        self.assertEqual(self.share(self.leader).status_code, 201)

        self.assertTrue(self.riuh_can_open())

    def test_a_leader_of_another_project_cannot_share(self):
        self.assertEqual(self.share(self.make_user("project_leader")).status_code, 403)

    def test_a_share_stops_working_after_it_expires(self):
        self.share(self.leader)
        DocumentShare.objects.update(expires_on=date.today() - timedelta(days=1))

        self.assertFalse(self.riuh_can_open())

    def test_expiry_in_the_past_is_rejected(self):
        self.assertEqual(self.share(self.leader, days=-1).status_code, 400)

    def test_revoking_removes_access_but_keeps_the_record(self):
        share_id = self.share(self.leader).data["id"]

        response = self.client_for(self.leader).post(f"/api/documents/documents/shares/{share_id}/revoke/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.riuh_can_open())
        self.assertIsNotNone(DocumentShare.objects.get().revoked_at)
