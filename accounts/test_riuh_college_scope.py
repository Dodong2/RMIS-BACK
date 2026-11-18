"""Client Task 85-A (2026-11-18): RIUH sees only its campus AND its College Unit (registration/profile), not every
college of the campus. The admin-set scope["college"] still wins. Other campus roles stay campus-only."""
from accounts.permissions import scoped_projects, visible_documents, visible_projects
from accounts.testing import RMISTestCase
from document_management.models import Document
from research_projects.models import Project

CAS = "CAS - College of Arts and Sciences"
CCS = "CCS - College of Computer Studies"


class RIUHCollegeScopeTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.cas = self._project("SIN-CAS", "Siniloan", CAS)
        self.ccs = self._project("SIN-CCS", "Siniloan", CCS)
        self.other_campus = self._project("LB-CAS", "Los Baños", CAS)

    def _project(self, code, campus, college):
        project = Project.objects.create(title=code, project_code=code, campus=campus, college=college,
                                         funding_type="externally_funded", lead=self.leader)
        Document.objects.create(project=project, document_type="ntp", sensitivity="project_team", version_number=1,
                                storage_path=f"x/{code}.pdf", file_name=f"{code}.pdf", file_size=1, uploaded_by=self.leader)
        return project

    def _ids(self, qs):
        return set(qs.values_list("pk", flat=True))

    def _doc_projects(self, user):
        return set(visible_documents(user, Document.objects.all()).values_list("project_id", flat=True))

    def test_riuh_sees_only_its_campus_and_college_unit(self):
        riuh = self.make_user("riuh", campus="Siniloan", college_unit=CAS)
        self.assertEqual(self._ids(visible_projects(riuh)), {self.cas.pk})
        self.assertEqual(self._ids(scoped_projects(riuh)), {self.cas.pk})
        self.assertEqual(self._doc_projects(riuh), {self.cas.pk})

    def test_riuh_without_college_unit_stays_campus_wide(self):
        riuh = self.make_user("riuh", campus="Siniloan")
        self.assertEqual(self._ids(visible_projects(riuh)), {self.cas.pk, self.ccs.pk})
        self.assertEqual(self._doc_projects(riuh), {self.cas.pk, self.ccs.pk})

    def test_admin_scope_college_still_wins(self):
        riuh = self.make_user("riuh", campus="Siniloan", college_unit=CAS, scope={"college": CCS})
        self.assertEqual(self._ids(visible_projects(riuh)), {self.ccs.pk})
        self.assertEqual(self._doc_projects(riuh), {self.ccs.pk})

    def test_other_campus_roles_ignore_their_college_unit(self):
        procurement = self.make_user("procurement_officer_lib", campus="Siniloan", college_unit=CAS)
        self.assertEqual(self._ids(scoped_projects(procurement)), {self.cas.pk, self.ccs.pk})
        crc = self.make_user("crc_chair", campus="Siniloan", college_unit=CAS)  # scoped_projects hides its drafts
        self.assertEqual(self._doc_projects(crc), {self.cas.pk, self.ccs.pk})

    def test_university_wide_roles_unchanged(self):
        vprei = self.make_user("vprei", college_unit=CAS)
        self.assertIsNone(visible_projects(vprei))
