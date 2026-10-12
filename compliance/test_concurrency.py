"""2026-10-12 concurrency audit: RIUH verification is stamped once, under a row lock."""
from accounts.testing import RMISTestCase
from compliance.models import EthicsReviewReference
from research_projects.models import Project


class VerifyOnceTests(RMISTestCase):
    def test_a_verified_record_keeps_its_first_verifier(self):
        leader = self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)
        record = EthicsReviewReference.objects.create(project=project, review_body="REC", recorded_by=leader)
        first, second = self.make_user("riuh"), self.make_user("system_admin")
        url = f"/api/compliance/ethics-reviews/{record.id}/verify/"

        self.assertEqual(self.client_for(first).post(url).status_code, 200)
        self.assertEqual(self.client_for(second).post(url).status_code, 400)
        record.refresh_from_db()
        self.assertEqual(record.verified_by, first)
