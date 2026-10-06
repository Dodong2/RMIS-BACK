from datetime import date, timedelta

import requests
from django.core.files.uploadedfile import SimpleUploadedFile

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


class DocumentUploadTests(RMISTestCase):
    """The research-documents bucket only accepts the MIME types set in the Supabase dashboard; a rejected upload
    used to surface as a 500 and demote the current version with nothing replacing it."""

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.make_user("project_leader"),
        )
        self.current = Document.objects.create(
            project=self.project, document_type="other", version_number=1, storage_path="P-1/other/v1_a.pdf",
            file_name="a.pdf", file_size=1, uploaded_by=self.admin,
        )

    def upload(self, name):
        return self.client_for(self.admin).post("/api/documents/documents/", {
            "project": self.project.id, "document_type": "other", "stage": "inception",
            "file": SimpleUploadedFile(name, b"data", content_type="application/octet-stream"),
        }, format="multipart")

    def test_an_allowed_file_becomes_the_new_current_version(self):
        response = self.upload("LIB.xlsx")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["version_number"], 2)
        self.assertEqual(
            response.data["content_type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.current.refresh_from_db()
        self.assertFalse(self.current.is_current)

    def test_an_unsupported_file_type_is_a_400_and_never_reaches_storage(self):
        response = self.upload("tool.exe")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)
        self.upload_document.assert_not_called()

    def test_a_storage_rejection_is_a_400_and_the_previous_version_stays_current(self):
        rejected = requests.Response()
        rejected.status_code, rejected._content = 400, b'{"message":"mime type image/png is not supported"}'
        self.upload_document.side_effect = requests.HTTPError(response=rejected)

        response = self.upload("scan.pdf")

        self.assertEqual(response.status_code, 400)
        self.assertIn("not supported", str(response.data["file"]))
        self.current.refresh_from_db()
        self.assertTrue(self.current.is_current)
        self.assertEqual(Document.objects.count(), 1)


class StagedUploadTests(RMISTestCase):
    """Register Approved Project uploads documents before the project exists, then trades the staged_token for a
    real Document once the project is created."""

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.make_user("project_leader"),
        )

    def stage(self, user, name="NOA.pdf"):
        return self.client_for(user).post("/api/documents/documents/staged/", {
            "file": SimpleUploadedFile(name, b"data", content_type="application/pdf"),
        }, format="multipart")

    def register(self, user, token):
        return self.client_for(user).post("/api/documents/documents/", {
            "project": self.project.id, "document_type": "other", "stage": "inception", "staged_token": token,
        })

    def test_a_staged_file_is_moved_into_the_project_on_register(self):
        staged = self.stage(self.admin)
        self.assertEqual(staged.status_code, 201)
        staged_path = self.upload_document.call_args.args[1]
        self.assertTrue(staged_path.startswith(f"_staged/{self.admin.id}/"))

        response = self.register(self.admin, staged.data["staged_token"])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["file_name"], "NOA.pdf")
        self.assertEqual(response.data["file_size"], 4)
        self.move_document.assert_called_once_with(staged_path, "P-1/other/v1_NOA.pdf")

    def test_an_unsupported_staged_file_is_rejected_before_storage(self):
        self.assertEqual(self.stage(self.admin, "tool.exe").status_code, 400)
        self.upload_document.assert_not_called()

    def test_another_users_token_or_a_forged_token_is_rejected(self):
        token = self.stage(self.admin).data["staged_token"]
        other = self.make_user("system_admin")

        self.assertEqual(self.register(other, token).status_code, 400)
        self.assertEqual(self.register(self.admin, token + "x").status_code, 400)
        self.move_document.assert_not_called()
