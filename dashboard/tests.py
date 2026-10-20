from accounts.testing import RMISTestCase
from research_projects.models import Project


class PortfolioDashboardTests(RMISTestCase):
    def test_program_leader_sees_counts_for_every_project(self):
        other = self.make_user("project_leader")
        program_leader = self.make_user("program_leader")
        Project.objects.create(
            title="A", project_code="A-1", funding_type="core_funded", lead=other, research_priority_area="ict",
            sdgs=[4, 9], campus="San Pablo City", college="CCS - College of Computer Studies",
        )
        Project.objects.create(
            title="B", project_code="B-1", funding_type="core_funded", lead=other, status="completed",
            sdgs=[9], campus="San Pablo City", college="CCS - College of Computer Studies",
        )

        response = self.client_for(program_leader).get("/api/dashboard/portfolio/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_projects"], 2)
        self.assertEqual(response.data["by_priority_area"], {"Information and Communication Tech.": 1, "Unspecified": 1})
        self.assertEqual(response.data["by_sdg"], {4: 1, 9: 2})
        self.assertEqual(response.data["by_college"], [{
            "college": "CCS - College of Computer Studies", "code": "CCS", "title": "College of Computer Studies",
            "campus": "San Pablo City", "total": 2, "by_status": {"active": 1, "completed": 1},
        }])

    def test_project_leader_sees_the_portfolio(self):
        response = self.client_for(self.make_user("project_leader")).get("/api/dashboard/portfolio/")

        self.assertEqual(response.status_code, 200)

    def test_study_leader_cannot_see_the_portfolio(self):
        response = self.client_for(self.make_user("study_leader")).get("/api/dashboard/portfolio/")

        self.assertEqual(response.status_code, 403)

    def test_campus_filter(self):
        leader = self.make_user("project_leader")
        Project.objects.create(title="A", project_code="A-1", funding_type="core_funded", lead=leader, campus="Siniloan")

        response = self.client_for(self.make_user("system_admin")).get("/api/dashboard/portfolio/", {"campus": "Sta. Cruz"})

        self.assertEqual(response.data["total_projects"], 0)


class CollegeFilterTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        leader = self.make_user("project_leader")
        for code, college in (("A-1", "CCS - College of Computer Studies"), ("B-1", "CA - College of Agriculture")):
            Project.objects.create(
                title=code, project_code=code, funding_type="core_funded", lead=leader, campus="San Pablo City",
                college=college,
            )
        self.client = self.client_for(self.make_user("system_admin"))

    def test_project_dashboard_filters_by_college(self):
        response = self.client.get("/api/dashboard/projects/", {"college": "CA - College of Agriculture"})

        self.assertEqual(response.data["total_projects"], 1)

    def test_portfolio_filters_by_college(self):
        response = self.client.get("/api/dashboard/portfolio/", {"college": "CCS - College of Computer Studies"})

        self.assertEqual(response.data["total_projects"], 1)

    def test_budget_and_outputs_accept_campus_and_college(self):
        budget = self.client.get("/api/dashboard/budget/", {"campus": "Siniloan"})
        outputs = self.client.get("/api/dashboard/outputs/", {"college": "CA - College of Agriculture"})

        self.assertEqual(budget.data["project_count"], 0)
        self.assertEqual(outputs.status_code, 200)

    def test_rei_thrust_alignment_follows_campus_and_college(self):
        """Client 2026-10-16: the restored REI Thrust tab follows the Analytics Campus/College filter."""
        Project.objects.filter(project_code="A-1").update(rei_thrust="REI-01 - Food Security")

        everything = self.client.get("/api/dashboard/rei-thrust-alignment/")
        ccs = self.client.get("/api/dashboard/rei-thrust-alignment/", {"college": "CCS - College of Computer Studies"})
        siniloan = self.client.get("/api/dashboard/rei-thrust-alignment/", {"campus": "Siniloan"})

        self.assertEqual((everything.data["by_thrust"], everything.data["unaligned_count"]), ({"REI-01 - Food Security": 1}, 1))
        self.assertEqual((ccs.data["by_thrust"], ccs.data["unaligned_count"]), ({"REI-01 - Food Security": 1}, 0))
        self.assertEqual((siniloan.data["by_thrust"], siniloan.data["unaligned_count"]), ({}, 0))


class PerformanceDashboardTests(RMISTestCase):
    """Analytics > Overview rankings (client 2026-10-14, prototype formula, provisional until the client confirms):
    score = 0.4 progress + 0.3 utilization + 0.2 completion rate + 0.1 min(100, outputs x 10)."""

    def _project(self, code, lead, campus, college, status="active", milestones=(0, 0), approved=0, spent=0, pubs=0):
        from datetime import date

        from budget_lib.models import LineItem, LineItemBudget
        from financial_monitoring.models import Disbursement
        from outputs.models import PublicationRecord
        from research_projects.models import WorkPlanMilestone

        project = Project.objects.create(
            title=f"Title {code}", project_code=code, funding_type="core_funded", lead=lead, campus=campus,
            college=college, status=status,
        )
        done, total = milestones
        for i in range(total):
            WorkPlanMilestone.objects.create(
                project=project, title=f"M{i}", target_date=date(2026, 1, 1), status="done" if i < done else "pending",
            )
        if approved:
            budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified")
            item = LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=approved)
            if spent:
                Disbursement.objects.create(line_item=item, amount=spent, disbursed_on=date(2026, 2, 1), recorded_by=lead)
        for i in range(pubs):
            PublicationRecord.objects.create(
                project=project, lead_author=lead, recorded_by=lead, title=f"P{i}", publication_type="journal_article",
                published_on=date(2026, 1, 1),
            )
        return project

    def setUp(self):
        super().setUp()
        self.reyes = self.make_user("project_leader", first_name="Jose", last_name="Reyes", position="Professor I")
        self.lim = self.make_user("project_leader", first_name="Cynthia", last_name="Lim")
        self._project("A-1", self.reyes, "San Pablo City", "CA - College of Agriculture",
                      milestones=(1, 2), approved=1000, spent=500, pubs=2)
        self._project("B-1", self.lim, "Siniloan", "CAS - College of Arts and Sciences",
                      status="completed", milestones=(4, 4), approved=1000, spent=1000, pubs=5)

    def test_project_rows_carry_physical_and_financial_progress(self):
        response = self.client_for(self.make_user("drd")).get("/api/dashboard/performance/")

        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data["projects"] if r["project_code"] == "A-1")
        self.assertEqual(row["physical_pct"], 50.0)
        self.assertEqual(row["financial_pct"], 50.0)
        self.assertEqual((row["milestones_done"], row["milestones_total"]), (1, 2))
        self.assertEqual(row["outputs"], 2)
        self.assertEqual(row["leader"], "Jose Reyes")
        self.assertEqual(row["leader_position"], "Professor I")
        self.assertEqual(row["college_code"], "CA")

    def test_rankings_use_the_weighted_score(self):
        data = self.client_for(self.make_user("drd")).get("/api/dashboard/performance/").data

        # A-1: 0.4*50 + 0.3*50 + 0.2*0 + 0.1*20 = 37; B-1: 0.4*100 + 0.3*100 + 0.2*100 + 0.1*50 = 95
        self.assertEqual([(c["campus"], c["score"]) for c in data["campus_ranking"]], [("Siniloan", 95), ("San Pablo City", 37)])
        self.assertEqual([c["code"] for c in data["college_ranking"]], ["CAS", "CA"])
        self.assertEqual([(l["leader"], l["score"]) for l in data["leader_ranking"]], [("Cynthia Lim", 95), ("Jose Reyes", 37)])
        self.assertEqual(data["leader_ranking"][1]["projects"], 1)

    def test_filters_by_campus_and_college(self):
        client = self.client_for(self.make_user("drd"))

        by_campus = client.get("/api/dashboard/performance/", {"campus": "Siniloan"}).data
        by_college = client.get("/api/dashboard/performance/", {"college": "CA - College of Agriculture"}).data

        self.assertEqual([r["project_code"] for r in by_campus["projects"]], ["B-1"])
        self.assertEqual([r["project_code"] for r in by_college["projects"]], ["A-1"])

    def test_project_without_milestones_or_budget_scores_zero_for_those_parts(self):
        self._project("C-1", self.make_user("project_leader"), "Sta. Cruz", "CTE - College of Teacher Education")

        data = self.client_for(self.make_user("drd")).get("/api/dashboard/performance/", {"campus": "Sta. Cruz"}).data

        row = data["projects"][0]
        self.assertIsNone(row["physical_pct"])
        self.assertIsNone(row["financial_pct"])
        self.assertEqual(data["campus_ranking"][0]["score"], 0)

    def test_rows_carry_funding_type_and_team_size(self):
        from research_projects.models import ProjectTeamMember

        project = Project.objects.get(project_code="A-1")
        ProjectTeamMember.objects.create(project=project, name="Ana Cruz", member_role="member")

        row = self.client_for(self.make_user("drd")).get("/api/dashboard/performance/").data["projects"][0]

        self.assertEqual((row["funding_type"], row["team_members"]), ("core_funded", 1))

    def test_monthly_disbursements_cover_the_latest_12_months_in_scope(self):
        client = self.client_for(self.make_user("drd"))

        months = client.get("/api/dashboard/performance/").data["monthly_disbursements"]
        siniloan = client.get("/api/dashboard/performance/", {"campus": "Siniloan"}).data["monthly_disbursements"]
        empty = client.get("/api/dashboard/performance/", {"campus": "Sta. Cruz"}).data["monthly_disbursements"]

        self.assertEqual(len(months), 12)
        self.assertEqual((months[0]["month"], months[-1]["month"]), ("2025-03", "2026-02"))
        self.assertEqual((months[-1]["total"], months[-1]["count"]), (1500.0, 2))
        self.assertEqual(siniloan[-1]["total"], 1000.0)
        self.assertEqual(empty, [])

    def test_budget_by_funding_agency_sums_current_lib_items_per_funding_source(self):
        from budget_lib.models import LineItem, LineItemBudget

        a1 = Project.objects.get(project_code="A-1")
        budget = LineItemBudget.objects.get(project=a1)
        LineItem.objects.filter(budget=budget).update(funding_source="DOST-PCAARRD")
        LineItem.objects.create(budget=budget, category="ps", description="Honoraria", amount=300, funding_source="LSPU GAA")
        old = LineItemBudget.objects.create(project=a1, version_number=2, is_current=False)
        LineItem.objects.create(budget=old, category="ps", description="Old", amount=9999, funding_source="CHED")
        client = self.client_for(self.make_user("drd"))

        everything = client.get("/api/dashboard/performance/").data["budget_by_funding_agency"]
        siniloan = client.get("/api/dashboard/performance/", {"campus": "Siniloan"}).data["budget_by_funding_agency"]

        # B-1's line item has no funding source; the old (non-current) LIB version is ignored.
        self.assertEqual(everything, [
            {"agency": "DOST-PCAARRD", "total": 1000.0},
            {"agency": "Unspecified", "total": 1000.0},
            {"agency": "LSPU GAA", "total": 300.0},
        ])
        self.assertEqual(siniloan, [{"agency": "Unspecified", "total": 1000.0}])

    def test_study_leader_cannot_see_performance(self):
        response = self.client_for(self.make_user("study_leader")).get("/api/dashboard/performance/")

        self.assertEqual(response.status_code, 403)


class ComplianceFilterTests(RMISTestCase):
    def test_compliance_dashboard_scopes_to_campus(self):
        from datetime import date

        from compliance.models import AIUseDeclaration

        leader = self.make_user("project_leader")
        project = Project.objects.create(title="A", project_code="A-1", funding_type="core_funded", lead=leader, campus="Siniloan")
        AIUseDeclaration.objects.create(
            project=project, declared_by=leader, ai_content_pct=5, declared_on=date(2026, 1, 1),
        )
        client = self.client_for(self.make_user("system_admin"))

        self.assertEqual(client.get("/api/dashboard/compliance/").data["ai_use_declarations"], 1)
        self.assertEqual(client.get("/api/dashboard/compliance/", {"campus": "Sta. Cruz"}).data["ai_use_declarations"], 0)


class ForecastingDashboardTests(RMISTestCase):
    def test_monthly_forecast_sums_the_latest_successful_run_per_project(self):
        from datetime import date

        from forecasting.models import ForecastRun, MonthlyForecast

        leader = self.make_user("project_leader")
        project = Project.objects.create(
            title="Smart Irrigation", project_code="A-1", funding_type="institutional", lead=leader,
            campus="Siniloan", college="CA - College of Agriculture",
        )
        old = ForecastRun.objects.create(project=project, run_by=leader, status="success")
        MonthlyForecast.objects.create(forecast_run=old, period=date(2026, 3, 1), predicted_amount=999, lower_bound=0, upper_bound=0)
        latest = ForecastRun.objects.create(project=project, run_by=leader, status="success")
        for month, amount in ((3, 100), (4, 200)):
            MonthlyForecast.objects.create(
                forecast_run=latest, period=date(2026, month, 1), predicted_amount=amount, lower_bound=0, upper_bound=0,
            )

        data = self.client_for(self.make_user("drd")).get("/api/dashboard/forecasting/", {"college": "CA - College of Agriculture"}).data

        self.assertEqual(data["monthly_forecast"], [{"month": "2026-03", "predicted": 100.0}, {"month": "2026-04", "predicted": 200.0}])
        self.assertEqual(data["projects"][0]["title"], "Smart Irrigation")


class DashboardRoleScopeTests(RMISTestCase):
    """Client 2026-10-20: the Dashboard counts only the projects the user can see (visible_projects); only
    university-wide roles get every project. Budget figures follow scoped_projects, so Project Staff get none."""

    def setUp(self):
        super().setUp()
        from datetime import date

        from compliance.models import AIUseDeclaration
        from personnel.models import Task
        from research_projects.models import ProjectTeamMember

        self.leader = self.make_user("project_leader")
        self.other_leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.mine = Project.objects.create(
            title="Mine", project_code="M-1", funding_type="core_funded", lead=self.leader, campus="San Pablo City",
        )
        self.other = Project.objects.create(
            title="Other", project_code="O-1", funding_type="core_funded", lead=self.other_leader, campus="Siniloan",
        )
        ProjectTeamMember.objects.create(project=self.mine, name="Staff", user=self.staff)
        for project in (self.mine, self.other):
            AIUseDeclaration.objects.create(
                project=project, declared_by=project.lead, ai_content_pct=5, declared_on=date(2026, 1, 1),
            )
            Task.objects.create(project=project, title="T", assigned_by=project.lead, assignee=project.lead)

    def get(self, user, path):
        return self.client_for(user).get(f"/api/{path}").data

    def test_project_staff_counts_only_projects_they_belong_to(self):
        self.assertEqual(self.get(self.staff, "dashboard/projects/")["total_projects"], 1)
        self.assertEqual(self.get(self.staff, "dashboard/compliance/")["ai_use_declarations"], 1)
        self.assertEqual([r["project"] for r in self.get(self.staff, "dashboard/tasks/")], [self.mine.pk])
        self.assertEqual(self.get(self.staff, "risk/dashboard/")["total_projects"], 1)

    def test_project_staff_get_no_budget_figures(self):
        self.assertEqual(self.get(self.staff, "dashboard/budget/")["project_count"], 0)

    def test_project_leader_counts_only_projects_they_lead(self):
        self.assertEqual(self.get(self.leader, "dashboard/projects/")["total_projects"], 1)
        self.assertEqual(self.get(self.leader, "dashboard/budget/")["project_count"], 1)
        self.assertEqual(self.get(self.leader, "dashboard/forecasting/")["projects_in_scope"], 1)

    def test_campus_scoped_role_counts_only_its_campus(self):
        crc = self.make_user("crc_chair", scope={"campus": "Siniloan"})

        self.assertEqual(self.get(crc, "dashboard/projects/")["by_campus"], {"Siniloan": 1})
        self.assertEqual(self.get(crc, "dashboard/compliance/")["ai_use_declarations"], 1)

    def test_university_wide_roles_count_every_project(self):
        for role in ("system_admin", "vprei"):
            user = self.make_user(role)
            self.assertEqual(self.get(user, "dashboard/projects/")["total_projects"], 2)
            self.assertEqual(self.get(user, "risk/dashboard/")["total_projects"], 2)
