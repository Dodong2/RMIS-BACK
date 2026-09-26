from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import AuditLog, Role, RolePermission, TemporaryReplacement, User
from accounts.permission_seed import PERMISSIONS
from accounts.permissions import scoped_projects
from accounts.testing import FAST_HASHER, PASSWORD, RMISTestCase
from research_projects.models import Project


@FAST_HASHER
class SeedRolesTests(TestCase):
    """A fresh database (new deploy, or the test DB) gets roles from seed_roles, which runs after migrate,
    so the permission-seeding migrations found no roles to grant to."""

    def test_seed_roles_also_grants_role_permissions(self):
        call_command("seed_roles", stdout=open("/dev/null", "w"))

        self.assertEqual(Role.objects.count(), 12)
        self.assertTrue(
            RolePermission.objects.filter(role__code="system_admin", permission__code="projects.register").exists()
        )

    def test_seeded_grants_match_every_permission_code(self):
        call_command("seed_roles", stdout=open("/dev/null", "w"))

        admin_codes = set(RolePermission.objects.filter(role__code="system_admin").values_list("permission__code", flat=True))
        self.assertEqual(admin_codes, set(PERMISSIONS))


class RegistrationTests(RMISTestCase):
    def register(self, **overrides):
        data = {"email": "New.Researcher@lspu.test", "password": PASSWORD, "password2": PASSWORD}
        data.update(overrides)
        return APIClient().post("/api/auth/register/", data, format="json")

    def test_register_creates_an_inactive_pending_user_and_emails_admins(self):
        self.make_user("system_admin", email="admin@lspu.test")
        role = Role.objects.get(code="project_leader")

        response = self.register(requested_role=role.id)

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="new.researcher@lspu.test")
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_pending_role)
        self.assertEqual(user.requested_role, role)
        self.assertTrue(self.brevo_post.called)

    def test_register_rejects_mismatched_passwords(self):
        response = self.register(password2="something-else")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="new.researcher@lspu.test").exists())

    def test_register_rejects_an_email_already_registered_in_any_case(self):
        self.register()

        response = self.register(email="NEW.RESEARCHER@LSPU.TEST")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.filter(email__iexact="new.researcher@lspu.test").count(), 1)

    def test_pending_user_cannot_log_in(self):
        self.register()

        response = APIClient().post(
            "/api/auth/login/", {"email": "new.researcher@lspu.test", "password": PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 400)


class AdminConfirmationTests(RMISTestCase):
    def test_admin_assigning_a_role_activates_the_user_and_sends_confirmation(self):
        admin = self.make_user("system_admin")
        pending = self.make_user(None, email="pending@lspu.test", is_active=False)
        role = Role.objects.get(code="project_leader")

        response = self.client_for(admin).patch(
            f"/api/admin/pending-users/{pending.id}/assign-role/", {"role_id": role.id}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertFalse(pending.is_pending_role)
        self.assertEqual(pending.role, role)
        self.assertTrue(self.brevo_post.called)

    def test_confirmed_user_can_then_log_in(self):
        admin = self.make_user("system_admin")
        pending = self.make_user(None, email="pending@lspu.test", is_active=False)
        self.client_for(admin).patch(
            f"/api/admin/pending-users/{pending.id}/assign-role/",
            {"role_id": Role.objects.get(code="project_leader").id}, format="json",
        )

        response = APIClient().post("/api/auth/login/", {"email": "pending@lspu.test", "password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200)

    def test_non_admin_cannot_assign_roles(self):
        leader = self.make_user("project_leader")
        pending = self.make_user(None, email="pending@lspu.test", is_active=False)

        response = self.client_for(leader).patch(
            f"/api/admin/pending-users/{pending.id}/assign-role/",
            {"role_id": Role.objects.get(code="system_admin").id}, format="json",
        )

        self.assertEqual(response.status_code, 403)
        pending.refresh_from_db()
        self.assertIsNone(pending.role)


class LoginAndTokenTests(RMISTestCase):
    def login(self, email, password=PASSWORD):
        return APIClient().post("/api/auth/login/", {"email": email, "password": password}, format="json")

    def test_login_returns_access_and_refresh_tokens_with_the_users_role(self):
        self.make_user("project_leader", email="leader@lspu.test")

        response = self.login("leader@lspu.test")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["role"]["code"], "project_leader")

    def test_login_is_case_insensitive_on_email(self):
        self.make_user("project_leader", email="leader@lspu.test")

        response = self.login("Leader@LSPU.test")

        self.assertEqual(response.status_code, 200)

    def test_login_rejects_a_wrong_password(self):
        self.make_user("project_leader", email="leader@lspu.test")

        response = self.login("leader@lspu.test", password="wrong-password")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access", response.data)

    def test_access_token_authenticates_api_requests(self):
        self.make_user("project_leader", email="leader@lspu.test")
        access = self.login("leader@lspu.test").data["access"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.get("/api/auth/user/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "leader@lspu.test")

    def test_api_rejects_requests_without_a_token(self):
        response = APIClient().get("/api/projects/")

        self.assertEqual(response.status_code, 401)

    def test_api_rejects_a_malformed_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

        response = client.get("/api/projects/")

        self.assertEqual(response.status_code, 401)

    def test_api_rejects_an_expired_access_token(self):
        user = self.make_user("project_leader")
        token = AccessToken.for_user(user)
        token.set_exp(lifetime=-timedelta(minutes=1))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get("/api/projects/")

        self.assertEqual(response.status_code, 401)

    def test_refresh_token_issues_a_new_access_token_and_rotates_the_refresh(self):
        self.make_user("project_leader", email="leader@lspu.test")
        refresh = self.login("leader@lspu.test").data["refresh"]

        response = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertNotEqual(response.data.get("refresh"), refresh)

    def test_refresh_rejects_a_garbage_token(self):
        response = APIClient().post("/api/auth/token/refresh/", {"refresh": "garbage"}, format="json")

        self.assertEqual(response.status_code, 401)


class PasswordResetTests(RMISTestCase):
    """dj-rest-auth's reset flow crashed (NoReverseMatch, and it would send through Django SMTP, which RMIS doesn't
    use — e-mail goes through Brevo). No frontend screen uses it, so it isn't exposed."""

    def test_password_reset_is_not_exposed(self):
        self.make_user("project_leader", email="leader@lspu.test")

        response = APIClient().post("/api/auth/password/reset/", {"email": "leader@lspu.test"}, format="json")

        self.assertEqual(response.status_code, 404)


class SuspensionTests(RMISTestCase):
    def test_suspended_users_existing_access_token_stops_working(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(leader)}")

        self.client_for(admin).post(f"/api/admin/users/{leader.id}/account-status/", {"action": "suspend"}, format="json")

        self.assertEqual(client.get("/api/projects/").status_code, 401)

    def test_suspended_user_cannot_refresh_their_session(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader")
        refresh = str(RefreshToken.for_user(leader))

        self.client_for(admin).post(f"/api/admin/users/{leader.id}/account-status/", {"action": "suspend"}, format="json")
        response = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")

        self.assertEqual(response.status_code, 401)

    def test_suspended_user_cannot_log_in(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader", email="leader@lspu.test")

        self.client_for(admin).post(f"/api/admin/users/{leader.id}/account-status/", {"action": "suspend"}, format="json")
        response = APIClient().post("/api/auth/login/", {"email": "leader@lspu.test", "password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_deactivation_is_blocked_while_the_user_still_leads_a_project(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader")
        Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)

        response = self.client_for(admin).post(
            f"/api/admin/users/{leader.id}/account-status/", {"action": "deactivate"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        leader.refresh_from_db()
        self.assertEqual(leader.account_status, "active")


class GoogleAuthTests(RMISTestCase):
    def supabase_says(self, status_code, email="g.user@lspu.test"):
        self.supabase_get.return_value = mock.Mock(
            status_code=status_code, text="{}", json=lambda: {"email": email, "id": "supabase-uid-1"}
        )

    def test_exchange_rejects_an_invalid_supabase_token(self):
        self.supabase_says(401)

        response = APIClient().post("/api/auth/google/exchange/", {"supabase_access_token": "x"}, format="json")

        self.assertEqual(response.status_code, 401)

    def test_exchange_gives_an_active_user_rmis_tokens(self):
        self.make_user("project_leader", email="g.user@lspu.test")
        self.supabase_says(200)

        response = APIClient().post("/api/auth/google/exchange/", {"supabase_access_token": "x"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    def test_exchange_refuses_a_pending_user(self):
        self.make_user(None, email="g.user@lspu.test", is_active=False)
        self.supabase_says(200)

        response = APIClient().post("/api/auth/google/exchange/", {"supabase_access_token": "x"}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_request_creates_a_pending_google_user(self):
        self.supabase_says(200)

        response = APIClient().post("/api/auth/google/request/", {"supabase_access_token": "x"}, format="json")

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="g.user@lspu.test")
        self.assertEqual(user.registration_method, "google")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())


class AuditLogTests(RMISTestCase):
    def test_authenticated_writes_are_audit_logged(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader")

        self.client_for(admin).patch(f"/api/admin/users/{leader.id}/scope/", {"campus": "Siniloan"}, format="json")

        log = AuditLog.objects.get()
        self.assertEqual((log.actor, log.method, log.status_code), (admin, "PATCH", 200))

    def test_reads_are_not_audit_logged(self):
        admin = self.make_user("system_admin")

        self.client_for(admin).get("/api/admin/users/")

        self.assertFalse(AuditLog.objects.exists())


class TemporaryReplacementTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.lead = self.make_user("project_leader")
        self.acting = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.lead)

    def replace(self):
        return self.client_for(self.admin).post("/api/admin/temporary-replacements/", {
            "suspended_user": self.lead.id, "replacement": self.acting.id,
            "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=30)),
        }, format="json")

    def suspend(self, action="suspend"):
        self.client_for(self.admin).post(f"/api/admin/users/{self.lead.id}/account-status/", {"action": action}, format="json")

    def test_only_a_suspended_user_can_be_replaced(self):
        self.assertEqual(self.replace().status_code, 400)

    def test_acting_leader_gets_the_suspended_leaders_projects(self):
        self.suspend()

        self.assertEqual(self.replace().status_code, 201)
        self.assertTrue(scoped_projects(self.acting).filter(pk=self.project.pk).exists())

    def test_reactivating_the_user_ends_the_replacement(self):
        self.suspend()
        self.replace()

        self.suspend("reactivate")

        self.assertIsNotNone(TemporaryReplacement.objects.get().ended_at)
        self.assertFalse(scoped_projects(self.acting).filter(pk=self.project.pk).exists())
