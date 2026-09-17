from rest_framework.permissions import BasePermission


class HasRole(BasePermission):
    def __init__(self, allowed_codes):
        self.allowed_codes = allowed_codes

    def __call__(self):
        return self

    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated
            and user.role is not None
            and user.role.code in self.allowed_codes
        )