from research_projects.models import Project

PROJECT_LIST_FIELDS = [
    "project_code", "title", "funding_type", "status", "campus",
    "rei_thrust", "start_date", "target_end_date", "total_cost",
]


def project_list_report(campus=None, funding_type=None, status=None, rei_thrust=None, year=None):
    """The docx's 'custom filtered report builder', scoped to a fixed set of
    Project fields rather than a fully generic query/column builder — a
    generic report designer is out of scope for this capstone; this covers
    the filters/fields RIUH/DRD would realistically ask for."""
    qs = Project.objects.all().select_related("lead")
    if campus:
        qs = qs.filter(campus=campus)
    if funding_type:
        qs = qs.filter(funding_type=funding_type)
    if status:
        qs = qs.filter(status=status)
    if rei_thrust:
        qs = qs.filter(rei_thrust=rei_thrust)
    if year:
        qs = qs.filter(start_date__year=year)

    rows = []
    for p in qs:
        rows.append(
            {
                "project_code": p.project_code,
                "title": p.title,
                "funding_type": p.funding_type,
                "status": p.status,
                "campus": p.campus,
                "rei_thrust": p.rei_thrust,
                "lead": p.lead.email if p.lead else "",
                "start_date": p.start_date,
                "target_end_date": p.target_end_date,
                "total_cost": p.total_cost,
            }
        )
    return rows
