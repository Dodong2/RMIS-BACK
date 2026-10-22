"""2026-10-22 real-time for project tasks: any saved or deleted Task, Work Log (TaskUpdate) or deliverable sends
"personnel.task.changed" {id, project} after commit (realtime/notify.py), so the leader's board/Work Plan and the
staff's dashboard refetch. Model receivers, not view calls: tasks are written from the board, Work Log, review,
deliverables and the Work Plan. A queryset .update() skips these; call task_signal() there yourself."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from realtime.notify import notify, project_audience

from .models import Task, TaskDeliverable, TaskUpdate


def task_signal(project, task_id, *user_ids):
    """To the task assigners' roles (leaders are reached per user), the project and program leads and the given users."""
    program_lead = project.program.lead_id if project.program_id else None
    users = [u for u in (program_lead, *user_ids) if u]
    notify(project_audience(project, "personnel.assign_tasks", *users), "personnel.task.changed", id=task_id,
           project=project.id)


def _changed(task):
    task_signal(task.project, task.id, task.assignee_id, task.assigned_by_id, task.study.lead_id if task.study_id else None)


@receiver([post_save, post_delete], sender=Task)
def task_saved(sender, instance, **kwargs):
    _changed(instance)


@receiver([post_save, post_delete], sender=TaskUpdate)
@receiver([post_save, post_delete], sender=TaskDeliverable)
def task_child_saved(sender, instance, **kwargs):
    try:
        _changed(instance.task)
    except Task.DoesNotExist:  # deleted together with its task, which sends its own signal
        pass
