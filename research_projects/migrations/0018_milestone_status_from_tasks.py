from django.db import migrations
from django.db.models import Sum


def status_from_tasks(apps, schema_editor):
    """Client 2026-10-21: a work plan activity's status follows its tasks (see WorkPlanMilestone.status_from_tasks).
    Historical models have no progress_pct, so a task at 100% is re-derived: Done, or the assignee's Work Log hours
    reaching its planned hours."""
    WorkPlanMilestone = apps.get_model("research_projects", "WorkPlanMilestone")
    Task = apps.get_model("personnel", "Task")
    TaskUpdate = apps.get_model("personnel", "TaskUpdate")

    def at_100(task):
        if task.status == "done":
            return True
        if not task.estimated_hours:
            return False
        logged = TaskUpdate.objects.filter(task=task, kind="update", author_id=task.assignee_id).aggregate(total=Sum("hours"))["total"] or 0
        return logged >= task.estimated_hours

    for milestone in WorkPlanMilestone.objects.all():
        flags = [at_100(task) for task in Task.objects.filter(milestone=milestone)]
        status = "pending" if not any(flags) else ("done" if all(flags) else "in_progress")
        if status != milestone.status:
            WorkPlanMilestone.objects.filter(pk=milestone.pk).update(status=status)


class Migration(migrations.Migration):
    dependencies = [
        ("research_projects", "0017_rename_rei_to_rde"),
        ("personnel", "0009_task_start_date"),
    ]

    operations = [migrations.RunPython(status_from_tasks, migrations.RunPython.noop)]
