from rest_framework.permissions import BasePermission


class HasAccess(BasePermission):
    def __init__(self, codes=None, tiers=None):
        self.codes = codes or []
        self.tiers = tiers or []

    def __call__(self):
        return self

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or user.role is None:
            return False
        return user.role.code in self.codes or user.role.tier in self.tiers