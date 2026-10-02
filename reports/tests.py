import csv
import io

import docx
import openpyxl

from accounts.testing import RMISTestCase
from monitoring.models import MidtermReport, TerminalReport
from outputs.models import ExpectedOutput
from research_projects.models import Project, ProjectEndorser

FORMATS = ("csv", "xlsx", "docx", "pdf")


def text_of(fmt, content):
    """Every word an export contains, so tests can check that all four formats carry the same form."""
    if fmt == "csv":
        return "\n".join(" ".join(row) for row in csv.reader(io.StringIO(content.decode())))
    if fmt == "xlsx":
        ws = openpyxl.load_workbook(io.BytesIO(content)).active
        return "\n".join(" ".join(str(v) for v in row if v is not None) for row in ws.iter_rows(values_only=True))
    if fmt == "docx":
        document = docx.Document(io.BytesIO(content))
        cells = [c.text for t in document.tables for r in t.rows for c in r.cells]
        footers = [p.text for section in document.sections for p in section.footer.paragraphs]
        return "\n".join([p.text for p in document.paragraphs] + cells + footers)
    return ""


class FormExportTests(RMISTestCase):
    """Client follow-up 2026-10-02: Appendix E follows LSPU-RDO-SF-017 and Appendix F follows SF-16, in every format."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Aimee", last_name="Chavez")
        self.admin = self.make_user("system_admin")
        self.project = Project.objects.create(
            title="Bridging Academia and Communities", project_code="BRIDGI-1", funding_type="institutional",
            lead=self.leader, objectives="1. Evaluate the status\n2. Prepare a report", background="Extension matters.",
            references="CHED. (2016). CMO 52.",
        )
        ExpectedOutput.objects.create(project=self.project, category="publications", description="Journal articles", target_count=10)
        ProjectEndorser.objects.create(project=self.project, name="Adriel G. Roman", designation="Dean/Associate Dean")

    def export(self, appendix, fmt, user=None):
        return self.client_for(user or self.leader).get(
            f"/api/reports/appendix-{appendix}/{self.project.pk}/", {"file_format": fmt}
        )

    def test_leader_saves_percent_per_objective_on_the_midterm(self):
        response = self.client_for(self.leader).post("/api/monitoring/midterm-reports/", {
            "project": self.project.pk, "project_year": 1,
            "objective_accomplishments": [{"objective": " Evaluate the status ", "q1": "25", "q2": 50, "q3": None, "q4": ""}],
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MidtermReport.objects.get().objective_accomplishments, [
            {"objective": "Evaluate the status", "q1": 25.0, "q2": 50.0, "q3": None, "q4": None},
        ])

    def test_percent_outside_0_to_100_is_rejected(self):
        response = self.client_for(self.leader).post("/api/monitoring/midterm-reports/", {
            "project": self.project.pk, "project_year": 1,
            "objective_accomplishments": [{"objective": "Evaluate", "q1": 120}],
        }, format="json")

        self.assertEqual(response.status_code, 400)

    def test_appendix_e_is_the_sf017_form_in_every_format(self):
        MidtermReport.objects.create(
            project=self.project, project_year=1, submitted_by=self.leader,
            objective_accomplishments=[{"objective": "Evaluate the status", "q1": 25, "q2": 50, "q3": None, "q4": None}],
        )

        for fmt in FORMATS:
            response = self.export("e", fmt)
            self.assertEqual(response.status_code, 200, fmt)
            if fmt == "pdf":
                self.assertTrue(response.content.startswith(b"%PDF"))
                continue
            text = text_of(fmt, response.content)
            for expected in ("MIDTERM/TERMINAL REPORT (FOR-LSPU-FUNDED PROJECT)", "SPECIFIC OBJECTIVES", "Evaluate the status",
                             "25%", "50%", "LSPU 6Ps Matrix", "Journal articles", "Actual: 0", "Aimee Chavez",
                             "Adriel G. Roman", "Dean/Associate Dean", "LSPU-RDO-SF-017"):
                self.assertIn(expected, text, f"{fmt}: {expected}")

    def test_appendix_e_without_percentages_lists_the_project_objectives(self):
        MidtermReport.objects.create(project=self.project, project_year=1, submitted_by=self.leader)

        text = text_of("csv", self.export("e", "csv").content)

        self.assertIn("Evaluate the status", text)
        self.assertIn("Prepare a report", text)

    def test_appendix_f_is_the_sf16_outline_in_every_format(self):
        TerminalReport.objects.create(project=self.project, narrative="We evaluated 12 projects.", submitted_by=self.leader)

        for fmt in FORMATS:
            response = self.export("f", fmt)
            self.assertEqual(response.status_code, 200, fmt)
            if fmt == "pdf":
                self.assertTrue(response.content.startswith(b"%PDF"))
                continue
            text = text_of(fmt, response.content)
            for expected in ("TERMINAL REPORT", "BRIDGI-1", "PRELIMINARY PAGES", "Executive Summary", "We evaluated 12 projects.",
                             "MAIN TEXT", "Project Rationale", "Extension matters.", "1. Evaluate the status",
                             "Results and Discussion", "Literature Cited", "CHED. (2016). CMO 52."):
                self.assertIn(expected, text, f"{fmt}: {expected}")

    def test_missing_reports_404(self):
        self.assertEqual(self.export("e", "pdf").status_code, 404)
        self.assertEqual(self.export("f", "pdf").status_code, 404)

    def test_other_leaders_cannot_export_the_project(self):
        TerminalReport.objects.create(project=self.project, submitted_by=self.leader)
        MidtermReport.objects.create(project=self.project, project_year=1, submitted_by=self.leader)
        other = self.make_user("project_leader")

        self.assertEqual(self.export("e", "csv", other).status_code, 404)
        self.assertEqual(self.export("f", "csv", other).status_code, 404)
        self.assertEqual(self.export("f", "csv", self.admin).status_code, 200)
