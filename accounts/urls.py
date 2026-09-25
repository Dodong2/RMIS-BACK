from django.urls import path
from .views import (
    UserAccountStatusView,
    AuditLogListView,
    RegisterView,
    GoogleRequestView,
    GoogleExchangeView,
    RolesListView,
    PendingUsersListView,
    UsersListView,
    UsersByRoleView,
    AssignRoleView,
    UpdateUserRoleView,
    ToggleUserActiveView,
    PermissionMatrixView,
    UserScopeView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/google/request/", GoogleRequestView.as_view()),
    path("auth/google/exchange/", GoogleExchangeView.as_view()),
    path("roles/", RolesListView.as_view()),
    path("users/by-role/", UsersByRoleView.as_view()),
    path("admin/pending-users/", PendingUsersListView.as_view()),
    path("admin/pending-users/<int:user_id>/assign-role/", AssignRoleView.as_view()),
    path("admin/users/", UsersListView.as_view()),
    path("admin/users/<int:user_id>/update-role/", UpdateUserRoleView.as_view()),
    path("admin/users/<int:user_id>/toggle-active/", ToggleUserActiveView.as_view()),
    path("admin/users/<int:user_id>/account-status/", UserAccountStatusView.as_view()),
    path("admin/audit-logs/", AuditLogListView.as_view()),
    path("admin/permissions/", PermissionMatrixView.as_view()),
    path("admin/users/<int:user_id>/scope/", UserScopeView.as_view()),
]