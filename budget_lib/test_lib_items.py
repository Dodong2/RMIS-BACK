"""Admin > LIB Items (client 2026-10-20): PS/MOOE/CO stay fixed; the System Admin maintains the items under each, and
LIB rows (wizard, Budget Management, realignment new items) pick only from the active ones."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .models import LibItem, LineItem, LineItemBudget

URL = "/api/budget/lib-items/"


class LibItemAdminTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("system_admin"))

    def test_starting_list_comes_from_uacs(self):
        honoraria = LibItem.objects.get(name="Honoraria")

        self.assertEqual((honoraria.category, honoraria.uacs_code), ("ps", "5010210000"))
        self.assertEqual(LibItem.objects.filter(category="co").count(), 5)

    def test_admin_adds_an_item_under_one_class(self):
        response = self.admin.post(URL, {"category": "mooe", "name": " Seminar Kits ", "uacs_code": "5020399000"}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["name"], response.data["is_active"]), ("Seminar Kits", True))

    def test_duplicates_are_refused_within_a_class_only(self):
        self.assertEqual(self.admin.post(URL, {"category": "ps", "name": "honoraria"}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(URL, {"category": "mooe", "name": "Honoraria"}, format="json").status_code, 201)

    def test_used_item_cannot_be_deleted_but_can_be_deactivated(self):
        leader = self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)
        budget = LineItemBudget.objects.create(project=project, version_number=1)
        LineItem.objects.create(budget=budget, category="ps", description="Honoraria", amount=Decimal("100"))
        item = LibItem.objects.get(name="Honoraria")

        self.assertEqual(self.admin.delete(f"{URL}{item.pk}/").status_code, 400)
        self.assertEqual(self.admin.patch(f"{URL}{item.pk}/", {"is_active": False}, format="json").status_code, 200)
        unused = LibItem.objects.get(name="Overtime Pay")
        self.assertEqual(self.admin.delete(f"{URL}{unused.pk}/").status_code, 204)

    def test_other_roles_only_read(self):
        leader = self.client_for(self.make_user("project_leader"))
        item = LibItem.objects.first()

        self.assertEqual(leader.get(URL).status_code, 200)
        self.assertEqual(leader.post(URL, {"category": "ps", "name": "X"}, format="json").status_code, 403)
        self.assertEqual(leader.patch(f"{URL}{item.pk}/", {"name": "X"}, format="json").status_code, 403)
        self.assertEqual(leader.delete(f"{URL}{item.pk}/").status_code, 403)


class LineItemCatalogTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader,
            start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=project, version_number=1)
        self.client = self.client_for(self.leader)

    def post(self, category, description):
        return self.client.post("/api/budget/line-items/", {
            "budget": self.budget.pk, "category": category, "description": description, "amount": "100",
        }, format="json")

    def test_item_must_be_an_active_item_of_its_class(self):
        ok = self.post("ps", "honoraria")

        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["description"], "Honoraria")
        self.assertEqual(self.post("mooe", "Honoraria").status_code, 400)
        self.assertEqual(self.post("mooe", "Snacks").status_code, 400)
        LibItem.objects.filter(name="Training Expenses").update(is_active=False)
        self.assertEqual(self.post("mooe", "Training Expenses").status_code, 400)

    def test_rows_encoded_before_the_catalog_keep_their_text(self):
        old = LineItem.objects.create(budget=self.budget, category="mooe", description="Snacks", amount=Decimal("100"))

        response = self.client.patch(f"/api/budget/line-items/{old.pk}/", {"amount": "100", "justification": "x"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        old.refresh_from_db()
        self.assertEqual(old.description, "Snacks")
