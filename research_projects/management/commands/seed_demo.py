"""
Three demo projects walked end to end (client request 2026-10-14: "kahit 3 complete end to end"), so the client can see
every module filled: registration (SF-018 fields, team, beneficiaries, endorsers, work plan, 6Ps) -> certified LIB ->
completed procurement that posted its disbursement -> other disbursements -> monthly reports -> approved quarterly report
-> outputs -> (2 of 3) certified terminal report and status changed to completed.

Every demo project code starts with DEMO-, so the data is easy to spot and remove:
    python manage.py seed_demo            # adds what is missing, skips demo projects that already exist
    python manage.py seed_demo --clear    # deletes every DEMO- project and everything under it

No accounts are created. Each step is done by the first active user holding the role that does it in the real flow;
if a role has no active user the command stops before writing anything.
"""

import datetime
from decimal import ROUND_DOWN, Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import BudgetRealignment, Disbursement, ProcurementRequest
from monitoring.models import MonthlyProgressReport, QuarterlyProgressReport, QuarterlyReportEvent, TerminalReport
from monitoring.quarterly import financial_snapshot, prefill_accomplishments
from outputs.models import ExpectedOutput, IPRecord, PublicationRecord
from research_projects.models import (
    CollegeUnit,
    Project,
    ProjectEndorser,
    ProjectStatusHistory,
    ProjectTeamMember,
    TargetBeneficiary,
    WorkPlanMilestone,
)

PREFIX = "DEMO-"
ROLES = ("project_leader", "finance_budget", "procurement_officer_lib", "riuh", "drd")
d = datetime.date

PROJECTS = [
    {
        "code": "DEMO-2026-001",
        "title": "Smart Irrigation Scheduling for Lowland Rice Farms in San Pablo City",
        "campus": "San Pablo City", "college": ("CA", "College of Agriculture"),
        "funding_type": "externally_funded", "funding_source": "DOST-PCAARRD",
        "priority": "agriculture_fisheries", "sectors": ["agriculture_fisheries"], "sdgs": [2, 6, 13],
        "typology": ["laboratory_field", "quasi_experimental"], "research_type": "applied",
        "rei_thrust": "Agriculture, Fisheries, and Food Security",
        "start": d(2025, 7, 1), "end": d(2026, 6, 30), "final_status": "completed",
        "objectives": "Measure soil moisture in 12 pilot paddies\nBuild an irrigation schedule model\nTrain farmer cooperators",
        "beneficiary": ("Rice farmer cooperators", 45),
        "items": [("ps", "Project technical assistant (12 months)", "180000"), ("mooe", "Field supplies and travel", "95000"),
                  ("co", "Soil moisture sensor kits", "125000")],
        "publication": ("Soil-moisture-based irrigation scheduling for lowland rice", "journal_article", "scopus"),
        "ip": ("Low-cost paddy soil moisture logger", "utility_model", "adopted"),
        "quarter": (2026, 2),
    },
    {
        "code": "DEMO-2026-002",
        "title": "Mobile Reading Tutor for Grade 3 Learners in Siniloan District",
        "campus": "Siniloan", "college": ("CTE", "College of Teacher Education"),
        "funding_type": "institutional", "funding_source": "LSPU GAA",
        "priority": "education_teacher_training", "sectors": ["education"], "sdgs": [4],
        "typology": ["quantitative", "development"], "research_type": "applied",
        "rei_thrust": "Education and Human Capital Development",
        "start": d(2025, 7, 1), "end": d(2026, 6, 30), "final_status": "completed",
        "objectives": "Assess reading levels of Grade 3 learners\nDevelop an offline mobile reading tutor\nMeasure reading gains after one semester",
        "beneficiary": ("Grade 3 learners and teachers", 160),
        "items": [("ps", "Research assistant (10 months)", "120000"), ("mooe", "Reading materials and school visits", "48000"),
                  ("co", "Android tablets for pilot classes", "72000")],
        "publication": ("Effects of an offline mobile reading tutor on Grade 3 reading fluency", "journal_article", "lspu_refereed"),
        "ip": None,
        "quarter": (2026, 2),
    },
    {
        "code": "DEMO-2026-003",
        "title": "IoT Water-Quality Monitoring for Laguna de Bay Fish Pens",
        "campus": "Los Baños", "college": ("CCS", "College of Computer Studies"),
        "funding_type": "externally_funded", "funding_source": "DOST-PCIEERD",
        "priority": "ict", "sectors": ["information_tech", "agriculture_fisheries"], "sdgs": [9, 14],
        "typology": ["development", "laboratory_field"], "research_type": "applied",
        "rei_thrust": "Information and Communication Technology",
        "start": d(2026, 1, 5), "end": d(2026, 12, 31), "final_status": "active",
        "objectives": "Deploy dissolved-oxygen and pH sensor buoys\nBuild an SMS alert dashboard\nEvaluate fish-kill early warnings",
        "beneficiary": ("Fish pen operators", 30),
        "items": [("ps", "IoT developer (12 months)", "216000"), ("mooe", "Boat rental, SIM load and field supplies", "84000"),
                  ("co", "Sensor buoys and gateway", "150000")],
        "publication": None,
        "ip": None,
        "quarter": (2026, 3),
    },
]


def _user(code):
    return (
        User.objects.filter(role__code=code, is_active=True, account_status="active", is_pending_role=False)
        .order_by("id").first()
    )


def _name(user):
    return user.get_full_name() or user.email


def _college(code, title):
    unit = CollegeUnit.objects.filter(code=code).first()
    return unit.name if unit else f"{code}{CollegeUnit.SEPARATOR}{title}"


def _months(start, count):
    return [d(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 1) for i in range(count)]


class Command(BaseCommand):
    help = "Add (or --clear) three DEMO- projects that go through the whole RMIS flow."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete every DEMO- project and its records.")

    def handle(self, *args, **options):
        if options["clear"]:
            self.clear()
            return
        users = {code: _user(code) for code in ROLES}
        missing = [code for code, user in users.items() if user is None]
        if missing:
            raise CommandError(f"No active user for role(s): {', '.join(missing)}. Add one, then run again.")
        with transaction.atomic():
            for spec in PROJECTS:
                if Project.objects.filter(project_code=spec["code"]).exists():
                    self.stdout.write(f"{spec['code']} already exists, skipped.")
                    continue
                self.seed_project(spec, users)
                self.stdout.write(self.style.SUCCESS(f"{spec['code']} created ({spec['final_status']})."))

    @transaction.atomic
    def clear(self):
        projects = Project.objects.filter(project_code__startswith=PREFIX)
        items = LineItem.objects.filter(budget__project__in=projects)
        # Disbursements, procurement and realignments PROTECT their line item, so they go first.
        Disbursement.objects.filter(line_item__in=items).delete()
        ProcurementRequest.objects.filter(line_item__in=items).delete()
        BudgetRealignment.objects.filter(from_line_item__in=items).delete()
        count = projects.count()
        projects.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} demo project(s)."))

    def seed_project(self, spec, users):
        leader, budget_officer, procurement, riuh, drd = (users[c] for c in ROLES)
        start, end = spec["start"], spec["end"]
        completed = spec["final_status"] == "completed"

        # 1. Registration (SF-018 + Annex A)
        project = Project.objects.create(
            title=spec["title"], project_code=spec["code"], funding_type=spec["funding_type"], lead=leader,
            status="active", start_date=start, target_end_date=end, rei_thrust=spec["rei_thrust"],
            ntp_number=f"NTP-{spec['code']}", ntp_date=start - datetime.timedelta(days=10), toe_signed_date=start,
            research_type=spec["research_type"], sectors=spec["sectors"], research_priority_area=spec["priority"],
            research_typology=spec["typology"], sdgs=spec["sdgs"], campus=spec["campus"],
            college=_college(*spec["college"]), implementing_unit=spec["college"][1],
            cooperating_agencies=spec["funding_source"], total_cost=sum(Decimal(a) for _, _, a in spec["items"]),
            lead_gender="female", contact_number="0917 000 0000",
            background="Demo record for walkthroughs (seed_demo). " + spec["title"] + ".",
            methodology="Baseline survey, prototype development, pilot deployment and evaluation.",
            socio_economic_significance="Shows the expected benefit to the target beneficiaries.",
            monitoring_evaluation="Monthly progress reports and quarterly reviews by the RIUH.",
            objectives=spec["objectives"], description=spec["title"],
            expected_outcomes="Adopted tool and trained beneficiaries.", expected_impacts="Better productivity in the community.",
            proposal_submitted_on=start - datetime.timedelta(days=90), proposal_reviewed_on=start - datetime.timedelta(days=60),
            proposal_approved_on=start - datetime.timedelta(days=30), reviewing_body="CRC",
            endorsed_by_dean="Dean, " + spec["college"][1], endorsed_by_dean_on=start - datetime.timedelta(days=80),
            approved_by_president="University President",
        )
        ProjectTeamMember.objects.create(project=project, member_role="co_leader", name="Demo Co-Leader", gender="male")
        ProjectTeamMember.objects.create(project=project, member_role="member", name="Demo Research Assistant", gender="female")
        TargetBeneficiary.objects.create(project=project, group=spec["beneficiary"][0], total=spec["beneficiary"][1])
        for user, designation in ((riuh, "Research and Innovation Unit Head"), (drd, "Director, Research and Development")):
            ProjectEndorser.objects.create(project=project, role_code=user.role.code, user=user, name=_name(user),
                                           designation=designation, signed_on=start - datetime.timedelta(days=40))

        # 2. Work plan + expected outputs (6Ps)
        span = (end - start).days
        objectives = [o for o in spec["objectives"].splitlines() if o]
        for i, (title, objective) in enumerate(zip(("Baseline data gathering", "Prototype development",
                                                    "Pilot deployment", "Evaluation and final report"), objectives * 2)):
            target = start + datetime.timedelta(days=span * (i + 1) // 4)
            status = "done" if completed or target < timezone.localdate() else ("in_progress" if i == 2 else "pending")
            WorkPlanMilestone.objects.create(
                project=project, title=title, start_date=start + datetime.timedelta(days=span * i // 4), target_date=target,
                status=status, objective=objective, deliverable=f"{title} completed", responsible=leader,
            )
        ExpectedOutput.objects.create(project=project, category="publications", description="One refereed journal article")
        ExpectedOutput.objects.create(project=project, category="people_services", description="Trained beneficiaries",
                                      target_count=spec["beneficiary"][1], manual_actual_count=spec["beneficiary"][1] if completed else 0)

        # 3. LIB, certified by the Budget Officer
        budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified",
                                               certified_by=budget_officer, certified_at=timezone.now())
        items = {
            category: LineItem.objects.create(
                budget=budget, category=category, description=description, amount=Decimal(amount), unit="lump_sum",
                quantity=1, unit_cost=Decimal(amount), fiscal_year=start.year, funding_source=spec["funding_source"],
                justification=f"Needed for: {description.lower()}.",
            )
            for category, description, amount in spec["items"]
        }

        # 4. Procurement of the CO item: received -> completed, which posts its disbursement
        co = items["co"]
        bought_on = start + datetime.timedelta(days=45)
        proc = ProcurementRequest.objects.create(
            line_item=co, description=co.description, amount=co.amount, fiscal_year=bought_on.year,
            quarter=(bought_on.month - 1) // 3 + 1, status="completed", requested_by=leader, received_by=procurement,
            received_at=timezone.now(), completed_at=timezone.now(), updated_by=procurement,
            remarks="Delivered and inspected.",
        )
        Disbursement.objects.create(line_item=co, amount=co.amount, reference_number=f"DV-{spec['code']}-CO",
                                    description=co.description, payee="Demo Supplier Inc.", disbursed_on=bought_on,
                                    recorded_by=procurement, procurement_request=proc)

        # 5. Monthly PS/MOOE disbursements up to the end date (or today for the active project)
        until = min(end, timezone.localdate())
        months = [m for m in _months(start, 12) if m <= until]
        share = Decimal("1") if completed else Decimal("0.85")
        for category in ("ps", "mooe"):
            item = items[category]
            each = (item.amount * share / 12).quantize(Decimal("0.01"), rounding=ROUND_DOWN)  # never over the line item
            for n, month in enumerate(months, 1):
                Disbursement.objects.create(line_item=item, amount=each, reference_number=f"DV-{spec['code']}-{category.upper()}-{n:02d}",
                                            description=item.description, payee="Demo payee", disbursed_on=min(month.replace(day=15), until),
                                            recorded_by=budget_officer)

        # 6. Monthly progress reports (the last three months of the period)
        for month in months[-3:]:
            MonthlyProgressReport.objects.create(project=project, period=month, submitted_by=leader,
                                                 narrative=f"Activities for {month:%B %Y} done as planned.")

        # 7. Quarterly progress report: leader prepares and submits, RIUH reviews and endorses, DRD approves
        year, quarter = spec["quarter"]
        report = QuarterlyProgressReport.objects.create(
            project=project, year=year, quarter=quarter, created_by=leader,
            accomplishments=[{**row, "actual": row["target"], "actual_date": row["target_date"], "cumulative": "100%"}
                             for row in prefill_accomplishments(project, year, quarter)],
            issues=[], financial_snapshot=financial_snapshot(project, year, quarter),
            recommendations="Continue as planned.",
        )
        QuarterlyReportEvent.objects.create(report=report, action="created", to_status="draft", actor=leader)
        for from_status, to_status, actor in (("draft", "submitted", leader), ("submitted", "under_review", riuh),
                                              ("under_review", "endorsed", riuh), ("endorsed", "approved", drd)):
            QuarterlyReportEvent.objects.create(report=report, action="status_transition", from_status=from_status,
                                                to_status=to_status, actor=actor)
        report.status, report.submitted_at, report.approved_by, report.approved_at = "approved", timezone.now(), drd, timezone.now()
        report.save()

        # 8. Outputs
        if spec["publication"]:
            title, kind, tier = spec["publication"]
            PublicationRecord.objects.create(project=project, lead_author=leader, title=title, publication_type=kind,
                                             indexing_tier=tier, published_on=end - datetime.timedelta(days=20),
                                             publisher_name="Demo Journal", recorded_by=leader)
        if spec["ip"]:
            title, kind, ip_status = spec["ip"]
            IPRecord.objects.create(project=project, creator=leader, title=title, ip_type=kind, status=ip_status, trl=7,
                                    is_adopted_by_community=ip_status == "adopted", recorded_by=leader,
                                    adoption_moa_reference="MOA-DEMO-001", registered_on=end - datetime.timedelta(days=30))

        # 9. Close-out: certified terminal report, then status -> completed
        if completed:
            TerminalReport.objects.create(project=project, submitted_by=leader, narrative="All objectives met.",
                                          is_certified=True, certified_by=riuh, certified_at=timezone.now())
            ProjectStatusHistory.objects.create(project=project, from_status="active", to_status="completed",
                                                changed_by=riuh, remarks="Terminal report certified.")
            project.status = "completed"
            project.save(update_fields=["status"])
