"""Checks that the DB permission table grants exactly what the old *_ROLES constants grant, for every code x role.
Run: python scripts/permission_parity.py   (exit code 1 if any difference)"""

import importlib
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from accounts.models import Permission, Role, RolePermission  # noqa: E402
from accounts.permission_seed import PERMISSIONS  # noqa: E402

role_codes = list(Role.objects.values_list("code", flat=True))
granted = set(RolePermission.objects.values_list("permission__code", "role__code"))
diffs = []

missing = set(PERMISSIONS) - set(Permission.objects.values_list("code", flat=True))
for code in sorted(missing):
    diffs.append(f"{code}: not in DB")

for code, (_module, _name, source) in PERMISSIONS.items():
    module_path, const = source.split(":")
    expected = set(getattr(importlib.import_module(module_path), const))
    for role in role_codes:
        in_constant = role in expected
        in_db = (code, role) in granted
        if in_constant != in_db:
            diffs.append(f"{code} / {role}: constant={in_constant} db={in_db}")

print(f"{len(role_codes)} roles x {len(PERMISSIONS)} permissions checked")
if len(role_codes) != 12:
    diffs.append(f"expected 12 roles in DB, found {len(role_codes)}")
for d in diffs:
    print("DIFF", d)
print(f"{len(diffs)} differences")
sys.exit(1 if diffs else 0)
