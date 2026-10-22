from django.apps import AppConfig


class PersonnelConfig(AppConfig):
    name = "personnel"

    def ready(self):
        from . import signals  # noqa: F401 — registers the real-time task receivers
