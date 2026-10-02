from datetime import date

from accounts.testing import RMISTestCase
from research_projects.models import Project
from risk_indicators.models import ProjectRisk


class RiskAlertTests(RMISTestCase):
    """Q7 actions as a live inbox: which risk levels each role is alerted about."""

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader")
        self.other_leader = self.make_user("project_leader")
        self.critical = self.project("CRIT", self.leader, likelihood=5, impact=5)
        self.high = self.project("HIGH", self.other_leader, likelihood=4, impact=4)
        self.medium = self.project("MED", self.leader, likelihood=3, impact=3)

    def project(self, code, lead, likelihood, impact):
        project = Project.objects.create(
            title=code, project_code=code, funding_type="core_funded", lead=lead, start_date=date.today(),
        )
        ProjectRisk.objects.create(
            project=project, description=code, category="technical", likelihood=likelihood, impact=impact,
            owner=self.admin, created_by=self.admin,
        )
        return project

    def alerts_for(self, user):
        response = self.client_for(user).get("/api/risk/alerts/")
        self.assertEqual(response.status_code, 200)
        return {(a["project_code"], a["risk_level"]) for a in response.data["alerts"]}

    def test_leader_gets_medium_and_up_on_their_own_projects_only(self):
        self.assertEqual(self.alerts_for(self.leader), {("CRIT", "critical"), ("MED", "medium")})

    def test_riuh_and_crc_get_high_and_critical(self):
        expected = {("CRIT", "critical"), ("HIGH", "high")}

        self.assertEqual(self.alerts_for(self.make_user("riuh")), expected)
        self.assertEqual(self.alerts_for(self.make_user("crc_chair")), expected)

    def test_vp_and_drd_get_critical_only(self):
        self.assertEqual(self.alerts_for(self.make_user("vprei")), {("CRIT", "critical")})
        self.assertEqual(self.alerts_for(self.make_user("drd")), {("CRIT", "critical")})

    def test_roles_without_a_q7_action_get_no_alerts(self):
        self.assertEqual(self.alerts_for(self.make_user("finance_budget")), set())

    def test_alerts_are_sorted_worst_first_with_bell_fields(self):
        alerts = self.client_for(self.admin).get("/api/risk/alerts/").data["alerts"]

        self.assertEqual([a["project_code"] for a in alerts], ["CRIT", "HIGH", "MED"])
        self.assertEqual(alerts[0]["type"], "danger")
        self.assertEqual(alerts[-1]["type"], "warning")


class OverdueMilestoneAlertTests(RMISTestCase):
    """Client meeting 2026-10-01 (#14): an overdue, not-done milestone shows in the leader's (and admin's) bell."""

    def test_overdue_milestone_alerts_the_leader_and_admin_only(self):
        import datetime

        from django.utils import timezone

        from research_projects.models import WorkPlanMilestone

        leader = self.make_user("project_leader")
        other_leader = self.make_user("project_leader")
        admin = self.make_user("system_admin")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="institutional", lead=leader)
        today = timezone.localdate()
        WorkPlanMilestone.objects.create(project=project, title="Data gathering", target_date=today - datetime.timedelta(days=5))
        WorkPlanMilestone.objects.create(project=project, title="Done one", target_date=today - datetime.timedelta(days=5), status="done")
        WorkPlanMilestone.objects.create(project=project, title="Future", target_date=today + datetime.timedelta(days=5))

        def milestone_alerts(user):
            alerts = self.client_for(user).get("/api/risk/alerts/").data["alerts"]
            return [a for a in alerts if a["kind"] == "milestone"]

        [alert] = milestone_alerts(leader)
        self.assertIn("Data gathering", alert["text"])
        self.assertEqual(alert["days_overdue"], 5)
        self.assertEqual(alert["link"], f"/work-plan?project={project.pk}")
        self.assertEqual(len(milestone_alerts(admin)), 1)
        self.assertEqual(milestone_alerts(other_leader), [])
