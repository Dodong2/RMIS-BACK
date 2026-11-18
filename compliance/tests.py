"""Client Task 79 (2026-11-18): Compliance is for System Admin, VP for REI and University Administration only, and
those three run all of it (encode, submit with an uploaded supporting document, review, verify)."""
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from compliance.models import ComplianceRequirement, EthicsReviewReference
from document_management.models import Document
from research_projects.models import Project

ALLOWED = ["system_admin", "vprei", "university_admin"]
DENIED = ["crc_chair", "riuh", "finance_budget", "procurement_officer_lib", "project_leader", "project_staff"]
LISTS = [
    "/api/compliance/requirements/", "/api/compliance/ethics-reviews/", "/api/compliance/similarity-checks/",
    "/api/compliance/ai-declarations/", "/api/compliance/coi-disclosures/", "/api/compliance/misconduct-cases/",
    "/api/dashboard/compliance/",
]


class ComplianceTestCase(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        # Active project (certified LIB): compliance records follow the existing work gate (Carl 2026-10-24, D5).
        LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")

    def requirement(self, responsible, by=None):
        response = self.client_for(by or responsible).post("/api/compliance/requirements/", {
            "project": self.project.id, "title": "Ethics clearance", "responsible": responsible.id, "deadline": "2026-12-31",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def upload(self, user):
        return self.client_for(user).post("/api/documents/documents/", {
            "project": self.project.id, "document_type": "other", "stage": "inception",
            "file": SimpleUploadedFile("evidence.pdf", b"%PDF-1.4 evidence", content_type="application/pdf"),
        }, format="multipart")


class RoleMatrixTests(ComplianceTestCase):
    def test_only_the_three_roles_can_read_compliance_and_its_dashboard(self):
        for code in ALLOWED + DENIED:
            client = self.client_for(self.make_user(code))
            for url in LISTS:
                expected = 200 if code in ALLOWED else 403
                self.assertEqual(client.get(url).status_code, expected, f"{code} {url}")

    def test_denied_roles_cannot_write_or_open_a_record_by_id(self):
        record = EthicsReviewReference.objects.create(project=self.project, review_body="REC", recorded_by=self.admin)
        req = ComplianceRequirement.objects.create(project=self.project, title="T", responsible=self.admin,
                                                   deadline="2026-12-31", created_by=self.admin)
        for code in DENIED:
            client = self.client_for(self.make_user(code))
            calls = {
                "detail": client.get(f"/api/compliance/ethics-reviews/{record.id}/"),
                "create": client.post("/api/compliance/ethics-reviews/", {"project": self.project.id, "review_body": "trc"}, format="json"),
                "ai declaration": client.post("/api/compliance/ai-declarations/", {"project": self.project.id}, format="json"),
                "verify": client.post(f"/api/compliance/ethics-reviews/{record.id}/verify/"),
                "submit": client.post(f"/api/compliance/requirements/{req.id}/submit/", {}, format="json"),
                "review": client.post(f"/api/compliance/requirements/{req.id}/review/", {"status": "compliant"}, format="json"),
            }
            for name, response in calls.items():
                self.assertEqual(response.status_code, 403, f"{code} {name}")

    def test_project_leader_responsible_for_an_old_requirement_is_blocked_too(self):
        # Requirements 8/9 on the shared DB name a Project Leader as responsible.
        req = ComplianceRequirement.objects.create(project=self.project, title="T", responsible=self.leader,
                                                   deadline="2026-12-31", created_by=self.admin)
        response = self.client_for(self.leader).post(f"/api/compliance/requirements/{req.id}/submit/", {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client_for(self.make_user("vprei")).post(
            f"/api/compliance/requirements/{req.id}/submit/", {}, format="json").status_code, 200)


class AllowedRoleWorkflowTests(ComplianceTestCase):
    def test_each_allowed_role_runs_the_requirement_flow_with_an_uploaded_document(self):
        for code in ALLOWED:
            user = self.make_user(code)
            req_id = self.requirement(user)
            uploaded = self.upload(user)
            self.assertEqual(uploaded.status_code, 201, f"{code} {uploaded.data}")
            client = self.client_for(user)
            submitted = client.post(f"/api/compliance/requirements/{req_id}/submit/", {"document": uploaded.data["id"]}, format="json")
            self.assertEqual((submitted.status_code, submitted.data["status"], submitted.data["document"]),
                             (200, "submitted", uploaded.data["id"]), code)
            doc = Document.objects.get(pk=uploaded.data["id"])
            self.assertEqual((doc.project_id, doc.uploaded_by_id), (self.project.id, user.id))
            again = client.post(f"/api/compliance/requirements/{req_id}/submit/", {"document": uploaded.data["id"]}, format="json")
            self.assertEqual(again.status_code, 400, code)  # a second click can't submit twice
            reviewed = client.post(f"/api/compliance/requirements/{req_id}/review/", {"status": "compliant"}, format="json")
            self.assertEqual((reviewed.status_code, reviewed.data["status"]), (200, "compliant"), code)
            self.assertEqual(client.get(f"/api/compliance/requirements/{req_id}/").data["document"], uploaded.data["id"])

    def test_each_allowed_role_encodes_and_verifies_records(self):
        for code in ALLOWED:
            client = self.client_for(self.make_user(code))
            ethics = client.post("/api/compliance/ethics-reviews/", {"project": self.project.id, "review_body": "trc"}, format="json")
            self.assertEqual(ethics.status_code, 201, f"{code} {ethics.data}")
            self.assertEqual(client.post(f"/api/compliance/ethics-reviews/{ethics.data['id']}/verify/").status_code, 200, code)
            case = client.post("/api/compliance/misconduct-cases/", {
                "project": self.project.id, "subject_name": "X", "case_type": "plagiarism", "referred_to": "Dean",
                "reported_on": "2026-11-18",
            }, format="json")
            self.assertEqual(case.status_code, 201, f"{code} {case.data}")

    def test_a_document_from_another_project_is_rejected(self):
        other = Project.objects.create(title="Q", project_code="Q-1", funding_type="core_funded", lead=self.leader)
        doc = Document.objects.create(project=other, document_type="other", version_number=1, storage_path="Q-1/o.pdf",
                                      file_name="o.pdf", file_size=1, uploaded_by=self.admin)
        req_id = self.requirement(self.admin)
        response = self.client_for(self.admin).post(f"/api/compliance/requirements/{req_id}/submit/", {"document": doc.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("document", response.data)

    def test_responsible_must_be_one_of_the_three_roles(self):
        for code in DENIED:
            response = self.client_for(self.admin).post("/api/compliance/requirements/", {
                "project": self.project.id, "title": "T", "responsible": self.make_user(code).id, "deadline": "2026-12-31",
            }, format="json")
            self.assertEqual(response.status_code, 400, code)
            self.assertIn("responsible", response.data)
        self.requirement(self.make_user("university_admin"), by=self.admin)


class AssignableUsersTests(ComplianceTestCase):
    def test_lists_only_active_accounts_of_the_three_roles_and_only_for_them(self):
        vprei, ua = self.make_user("vprei"), self.make_user("university_admin")
        inactive = self.make_user("vprei", is_active=False)
        self.make_user("riuh")
        response = self.client_for(vprei).get("/api/compliance/assignable-users/")
        self.assertEqual(response.status_code, 200)
        ids = {u["id"] for u in response.data}
        self.assertEqual(ids, {self.admin.id, vprei.id, ua.id})
        self.assertNotIn(inactive.id, ids)
        for code in DENIED:
            self.assertEqual(self.client_for(self.make_user(code)).get("/api/compliance/assignable-users/").status_code, 403, code)


class PermissionParityTests(RMISTestCase):
    def test_migrated_grants_match_the_seed_source(self):
        from accounts.models import RolePermission
        from compliance.serializers import COMPLIANCE_ROLES, ENCODE_ROLES, MANAGE_ROLES

        for code, roles in (("compliance.view", COMPLIANCE_ROLES), ("compliance.encode", ENCODE_ROLES), ("compliance.manage", MANAGE_ROLES)):
            granted = set(RolePermission.objects.filter(permission__code=code).values_list("role__code", flat=True))
            self.assertEqual(granted, set(ALLOWED), code)
            self.assertEqual(set(roles), set(ALLOWED), code)
