from accounts.testing import RMISTestCase
from research_projects.models import FundingType, Project


class FundingTypeTests(RMISTestCase):
    """Client meeting 2026-10-14: the System Admin manages the Funding Type dropdown."""

    def setUp(self):
        for code, name in (("institutional", "Institutional (LSPU-Funded)"), ("core_funded", "Core-Funded (Self-Funded)")):
            FundingType.objects.get_or_create(code=code, defaults={"name": name, "is_system": True})
        self.admin = self.client_for(self.make_user("system_admin"))

    def test_admin_adds_a_type_and_its_code_is_made_from_the_name(self):
        first = self.admin.post("/api/funding-types/", {"name": "LGU-Funded"}, format="json")
        again = self.admin.post("/api/funding-types/", {"name": "lgu-funded"}, format="json")
        clash = self.admin.post("/api/funding-types/", {"name": "LGU Funded"}, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual((first.data["code"], first.data["is_system"]), ("lgu_funded", False))
        self.assertEqual(again.status_code, 400)
        self.assertEqual(clash.data["code"], "lgu_funded_2")

    def test_only_the_system_admin_edits_the_list(self):
        leader = self.client_for(self.make_user("project_leader"))

        self.assertEqual(leader.get("/api/funding-types/").status_code, 200)
        self.assertEqual(leader.post("/api/funding-types/", {"name": "Grant"}, format="json").status_code, 403)

    def test_rename_keeps_the_code_and_system_or_used_types_cant_be_deleted(self):
        system = FundingType.objects.get(code="institutional")
        used = FundingType.objects.create(code="lgu_funded", name="LGU-Funded")
        unused = FundingType.objects.create(code="ngo_funded", name="NGO-Funded")
        Project.objects.create(title="P", project_code="P-1", funding_type="lgu_funded", lead=self.make_user("project_leader"))

        renamed = self.admin.patch(f"/api/funding-types/{system.pk}/", {"name": "LSPU-Funded", "code": "x"}, format="json")
        system_delete = self.admin.delete(f"/api/funding-types/{system.pk}/")
        used_delete = self.admin.delete(f"/api/funding-types/{used.pk}/")
        unused_delete = self.admin.delete(f"/api/funding-types/{unused.pk}/")

        self.assertEqual(renamed.status_code, 200, renamed.data)
        self.assertEqual((renamed.data["name"], renamed.data["code"]), ("LSPU-Funded", "institutional"))
        self.assertEqual(system_delete.status_code, 400)
        self.assertEqual(used_delete.status_code, 400)
        self.assertEqual(unused_delete.status_code, 204)

    def test_projects_accept_admin_types_and_refuse_unknown_ones(self):
        FundingType.objects.create(code="lgu_funded", name="LGU-Funded")
        leader = self.make_user("project_leader")
        base = {"title": "P", "lead": leader.pk, "sdgs": [4], "sectors": ["education"]}

        added = self.admin.post("/api/projects/", {**base, "project_code": "P-1", "funding_type": "lgu_funded"}, format="json")
        unknown = self.admin.post("/api/projects/", {**base, "project_code": "P-2", "funding_type": "nope"}, format="json")

        self.assertEqual(added.status_code, 201, added.data)
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("funding_type", unknown.data)
