from django.urls import path
from .views import (
    RegisterView,
    GoogleRequestView,
    GoogleExchangeView,
    RolesListView,
    PendingUsersListView,
    UsersListView,
    AssignRoleView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/google/request/", GoogleRequestView.as_view()),
    path("auth/google/exchange/", GoogleExchangeView.as_view()),
    path("roles/", RolesListView.as_view()),
    path("admin/pending-users/", PendingUsersListView.as_view()),
    path("admin/pending-users/<int:user_id>/assign-role/", AssignRoleView.as_view()),
    path("admin/users/", UsersListView.as_view()),
]