"""Client Task 29-A: III. Objectives is a rich-text numbered list; every reader still gets one plain text per objective."""
from django.test import SimpleTestCase

from accounts.testing import RMISTestCase
from monitoring.quarterly import objective_list
from reports.forms import _objectives
from research_projects.models import Project
from research_projects.serializers import objective_items

RICH = (
    "<ol><li><p>Evaluate the <strong>status</strong> of extension&nbsp;projects</p></li>"
    "<li><p>Prepare a report</p><ul><li>for the RDO</li></ul></li><li><p></p></li></ol>"
)


class ObjectiveItemsTests(SimpleTestCase):
    def test_rich_text_gives_one_item_per_top_level_entry(self):
        self.assertEqual(objective_items(RICH), ["Evaluate the status of extension projects", "Prepare a report for the RDO"])

    def test_plain_text_keeps_the_old_reading(self):
        self.assertEqual(objective_items("1. Evaluate the status\n\n2) Prepare a report\n"), ["Evaluate the status", "Prepare a report"])
        self.assertEqual(objective_items("Characterize biochar\nDevelop a package"), ["Characterize biochar", "Develop a package"])

    def test_paragraphs_without_a_list_are_one_item_each(self):
        self.assertEqual(objective_items("<p>First &amp; foremost</p><p>Second<br>Third</p>"), ["First & foremost", "Second", "Third"])

    def test_empty_values(self):
        for value in (None, "", "<p></p>", "<ol><li><p></p></li></ol>"):
            self.assertEqual(objective_items(value), [])

    def test_quarterly_list_keeps_plain_lines_and_numbers_rich_text(self):
        self.assertEqual(objective_list(Project(objectives="1. Evaluate the status\nPrepare")), ["1. Evaluate the status", "Prepare"])
        self.assertEqual(objective_list(Project(objectives=RICH)),
                         ["1. Evaluate the status of extension projects", "2. Prepare a report for the RDO"])

    def test_report_forms_read_both(self):
        self.assertEqual(_objectives(Project(objectives=RICH))[0], "Evaluate the status of extension projects")
        self.assertEqual(_objectives(Project(objectives="1. Evaluate the status")), ["Evaluate the status"])


class ObjectiveSanitizeTests(RMISTestCase):
    def test_saved_objectives_are_sanitized_and_keep_the_list(self):
        admin, leader = self.make_user("system_admin"), self.make_user("project_leader")
        project = Project.objects.create(title="Old", project_code="OLD-1", funding_type="core_funded", lead=leader,
                                         sdgs=[4], sectors=["education"])

        response = self.client_for(admin).patch(f"/api/projects/{project.pk}/", {
            "objectives": '<ol><li><p onclick="x()">Evaluate <strong>status</strong></p></li><script>alert(1)</script></ol>',
        }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        project.refresh_from_db()
        self.assertNotIn("script", project.objectives)
        self.assertNotIn("onclick", project.objectives)
        self.assertIn("<li><p>Evaluate <strong>status</strong></p></li>", project.objectives)
        self.assertEqual(objective_items(project.objectives), ["Evaluate status"])
