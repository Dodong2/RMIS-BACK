from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import AuditLog, Role, RolePermission, TemporaryReplacement, User
from accounts.permission_seed import PERMISSIONS
from accounts.permissions import scoped_projects
from accounts.testing import FAST_HASHER, PASSWORD, RMISTestCase
from research_projects.models import CollegeUnit, Project


@FAST_HASHER
class SeedRolesTests(TestCase):
    """A fresh database (new deploy, or the test DB) gets roles from seed_roles, which runs after migrate,
    so the permission-seeding migrations found no roles to grant to."""

    def test_seed_roles_also_grants_role_permissions(self):
        call_command("seed_roles", stdout=open("/dev/null", "w"))

        self.assertEqual(Role.objects.count(), 9)  # 12 became 9 (client 2026-10-27)
        self.assertEqual(Role.objects.get(code="crc_chair").name, "CRC/CRD")
        self.assertEqual(Role.objects.get(code="project_leader").name, "Project Leader/Program Leader/Study Leader")
        self.assertFalse(Role.objects.filter(code__in=["drd", "program_leader", "study_leader"]).exists())
        self.assertTrue(
            RolePermission.objects.filter(role__code="system_admin", permission__code="projects.register").exists()
        )

    def test_seeded_grants_match_every_permission_code(self):
        call_command("seed_roles", stdout=open("/dev/null", "w"))

        admin_codes = set(RolePermission.objects.filter(role__code="system_admin").values_list("permission__code", flat=True))
        # Client 2026-10-11 (accounts 0016/0017): system_admin only approves, so it doesn't encode LIBs or file realignments.
        # 2026-10-14 (accounts 0021): quarterly reports follow Structure Module 9, which has no system_admin.
        self.assertEqual(admin_codes, set(PERMISSIONS) - {
            "budget.manage", "financial.request_realignment",
            "monitoring.quarterly_prepare", "monitoring.quarterly_review", "monitoring.quarterly_approve",
        })


class MergeRolesMigrationTests(RMISTestCase):
    """accounts 0026 (client 2026-10-27): accounts on DRD/Program/Study Leader move to CRC/CRD and Project Leader."""

    def test_legacy_accounts_move_to_the_merged_role_and_legacy_grants_go(self):
        import importlib

        from django.apps import apps

        from accounts.models import Permission
        from research_projects.models import ProjectEndorser

        merge = importlib.import_module("accounts.migrations.0026_merge_roles")
        legacy = {code: Role.objects.create(code=code, name=code) for code in merge.MERGED}
        RolePermission.objects.create(role=legacy["drd"], permission=Permission.objects.get(code="dss.manage"))
        drd = self.make_user(None, email="drd@lspu.test")
        User.objects.filter(pk=drd.pk).update(role=legacy["drd"])
        study = self.make_user(None, email="study@lspu.test")
        User.objects.filter(pk=study.pk).update(requested_role=legacy["study_leader"])
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded",
                                         lead=self.make_user("project_leader"))
        endorser = ProjectEndorser.objects.create(project=project, role_code="drd", name="Dr. D")

        merge.forwards(apps, None)

        drd.refresh_from_db()
        study.refresh_from_db()
        endorser.refresh_from_db()
        self.assertEqual((drd.role.code, study.requested_role.code, endorser.role_code),
                         ("crc_chair", "project_leader", "crc_chair"))
        self.assertFalse(RolePermission.objects.filter(role__in=legacy.values()).exists())
        self.assertEqual(Role.objects.get(code="crc_chair").name, "CRC/CRD")
        crc = set(RolePermission.objects.filter(role__code="crc_chair").values_list("permission__code", flat=True))
        self.assertNotIn("dss.manage", crc)  # none of DRD's own permissions (client 2026-10-27, a-g)
        self.assertNotIn("projects.register", crc)


class DeleteLegacyRolesMigrationTests(RMISTestCase):
    """accounts 0027 (client 2026-10-27): the legacy roles go once no account has them."""

    def setUp(self):
        super().setUp()
        import importlib

        self.migration = importlib.import_module("accounts.migrations.0027_delete_legacy_roles")
        for code in self.migration.LEGACY:
            Role.objects.create(code=code, name=code)

    def test_deletes_the_legacy_roles_and_keeps_the_nine(self):
        from django.apps import apps

        self.migration.forwards(apps, None)

        self.assertFalse(Role.objects.filter(code__in=self.migration.LEGACY).exists())
        self.assertEqual(Role.objects.count(), 9)

    def test_stops_while_an_account_still_has_a_legacy_role(self):
        from django.apps import apps

        user = self.make_user(None)
        User.objects.filter(pk=user.pk).update(requested_role=Role.objects.get(code="study_leader"))

        with self.assertRaisesMessage(RuntimeError, "still have a legacy role"):
            self.migration.forwards(apps, None)
        self.assertEqual(Role.objects.filter(code__in=self.migration.LEGACY).count(), 3)


class RegistrationTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        CollegeUnit.objects.create(code="CCS", title="College of Computer Studies")

    def register(self, **overrides):
        data = {
            "email": "New.Researcher@lspu.test", "password": PASSWORD, "password2": PASSWORD,
            "first_name": "Aimee Concepcion", "last_name": "Chavez", "gender": "female", "campus": "Siniloan",
            "college_unit": "CCS - College of Computer Studies", "mobile_number": "09171234567", "staff_id": "123456",
            "requested_role": Role.objects.get(code="project_staff").id,
        }
        data.update(overrides)
        return APIClient().post("/api/auth/register/", data, format="json")

    def test_register_stores_the_new_required_fields(self):
        response = self.register(mobile_number="+639171234567")

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="new.researcher@lspu.test")
        self.assertEqual(
            (user.gender, user.campus, user.college_unit, user.mobile_number, user.staff_id, user.requested_role.code),
            ("female", "Siniloan", "CCS - College of Computer Studies", "+639171234567", "123456", "project_staff"),
        )
        self.assertIsNone(user.email_verified_at)

    def test_every_new_field_is_required(self):
        for field in ("gender", "campus", "college_unit", "mobile_number", "staff_id", "requested_role"):
            with self.subTest(field=field):
                response = self.register(**{field: ""})

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertFalse(User.objects.filter(email="new.researcher@lspu.test").exists())

    def test_register_rejects_values_outside_the_lists_and_formats(self):
        cases = [
            ("gender", "other"), ("campus", "Manila"), ("college_unit", "College of Nowhere"),
            ("mobile_number", "0917123456"), ("staff_id", "12345"), ("staff_id", "abcdef"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                response = self.register(**{field: value})

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertFalse(User.objects.filter(email="new.researcher@lspu.test").exists())

    def test_system_admin_cannot_be_requested(self):
        response = self.register(requested_role=Role.objects.get(code="system_admin").id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("requested_role", response.data)

    def test_staff_id_must_be_unique(self):
        self.make_user("project_leader", staff_id="123456")

        response = self.register()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["staff_id"], ["This Staff ID is already registered."])

    def test_register_runs_the_password_rules(self):
        for weak in ("short1", "12345678901", "password123"):
            with self.subTest(password=weak):
                response = self.register(password=weak, password2=weak)

                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(email="new.researcher@lspu.test").exists())

    def test_registration_options_are_public_and_never_offer_system_admin(self):
        response = APIClient().get("/api/auth/registration-options/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["campuses"], ["San Pablo City", "Siniloan", "Los Baños", "Sta. Cruz"])
        self.assertEqual(response.data["college_units"], ["CCS - College of Computer Studies"])
        codes = [role["code"] for role in response.data["roles"]]
        self.assertNotIn("system_admin", codes)
        self.assertEqual(len(codes), Role.objects.count() - 1)
        self.assertEqual([g["value"] for g in response.data["genders"]], ["male", "female"])

    def test_register_creates_an_inactive_pending_user_and_emails_only_the_registrant(self):
        self.make_user("system_admin", email="admin@lspu.test")
        role = Role.objects.get(code="project_leader")

        response = self.register(requested_role=role.id)

        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="new.researcher@lspu.test")
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_pending_role)
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(user.requested_role, role)
        self.assertEqual(user.get_full_name(), "Aimee Concepcion Chavez")
        # Approach C (2026-10-27): only the verification e-mail goes out; admins hear about it after verification.
        recipients = [call.kwargs["json"]["to"][0]["email"] for call in self.brevo_post.call_args_list]
        self.assertEqual(recipients, ["new.researcher@lspu.test"])
        self.assertTrue(AuditLog.objects.filter(actor=user, path="/api/auth/register/", status_code=201).exists())

    def test_register_needs_a_first_and_last_name(self):
        response = self.register(last_name="  ")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="new.researcher@lspu.test").exists())

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


class EmailVerificationTests(RMISTestCase):
    """Approach C (client 2026-10-27): register -> verify the e-mail -> System Admin approval -> log in."""

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin", email="admin@lspu.test")
        self.user = self.make_user(None, email="new@lspu.test", is_active=False, first_name="New", last_name="User")

    def link(self, user=None):
        from accounts.tokens import verification_link_params

        uid, token = verification_link_params(user or self.user)
        return {"uid": uid, "token": token}

    def verify(self, data):
        with self.captureOnCommitCallbacks(execute=True):
            return APIClient().post("/api/auth/verify-email/", data, format="json")

    def sent_to(self):
        return [call.kwargs["json"]["to"][0]["email"] for call in self.brevo_post.call_args_list]

    def test_the_e_mailed_link_verifies_the_address_and_then_notifies_admins(self):
        from accounts.emails import send_verification_email

        send_verification_email(self.user)
        html = self.brevo_post.call_args.kwargs["json"]["htmlContent"]
        self.assertIn("/verify-email?uid=", html)
        self.brevo_post.reset_mock()

        response = self.verify(self.link())

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertFalse(self.user.is_active)  # still needs the System Admin's approval
        self.assertEqual(self.sent_to(), ["admin@lspu.test"])

    def test_a_link_works_only_once(self):
        link = self.link()
        self.verify(link)
        self.brevo_post.reset_mock()

        response = self.verify(link)

        self.assertEqual(response.status_code, 400)
        self.brevo_post.assert_not_called()

    def test_a_link_expires_after_48_hours(self):
        from datetime import datetime

        from accounts.tokens import email_verification_token

        link = self.link()
        later = datetime.now() + timedelta(hours=48, minutes=1)
        with mock.patch.object(email_verification_token, "_now", return_value=later):
            response = self.verify(link)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.email_verified_at)

    def test_a_token_for_another_account_or_garbage_is_refused(self):
        other = self.make_user(None, email="other@lspu.test", is_active=False)
        for data in ({**self.link(), "uid": self.link(other)["uid"]}, {"uid": "!!", "token": "x"}, {}):
            with self.subTest(data=data):
                self.assertEqual(self.verify(data).status_code, 400)
        self.assertFalse(User.objects.filter(email_verified_at__isnull=False, is_pending_role=True).exists())

    def test_resend_answers_the_same_whether_or_not_the_address_is_registered(self):
        unknown = APIClient().post("/api/auth/resend-verification/", {"email": "nobody@lspu.test"}, format="json")
        known = APIClient().post("/api/auth/resend-verification/", {"email": "NEW@lspu.test"}, format="json")

        self.assertEqual((unknown.status_code, unknown.data), (known.status_code, known.data))
        self.assertEqual(self.sent_to(), ["new@lspu.test"])

    def test_resend_skips_verified_or_confirmed_accounts(self):
        self.verify(self.link())
        self.brevo_post.reset_mock()
        for email in ("new@lspu.test", "admin@lspu.test"):
            APIClient().post("/api/auth/resend-verification/", {"email": email}, format="json")

        self.brevo_post.assert_not_called()

    def test_login_says_why_only_when_the_password_is_right(self):
        def login(password=PASSWORD):
            return APIClient().post("/api/auth/login/", {"email": "new@lspu.test", "password": password}, format="json")

        unverified = login()
        wrong_password = login("not-the-password")
        self.verify(self.link())
        pending = login()
        User.objects.filter(pk=self.user.pk).update(account_status="rejected", is_pending_role=False)
        rejected = login()

        self.assertEqual(unverified.status_code, 400)
        self.assertEqual(unverified.data["account_state"], ["unverified"])
        self.assertNotIn("account_state", wrong_password.data)
        self.assertEqual(pending.data["account_state"], ["pending_approval"])
        self.assertEqual(rejected.data["account_state"], ["rejected"])

    def test_refresh_of_a_deleted_account_is_401_not_500(self):
        refresh = str(RefreshToken.for_user(self.admin))
        User.objects.filter(pk=self.admin.pk).delete()

        response = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")

        self.assertEqual(response.status_code, 401)


class PendingDecisionTests(RMISTestCase):
    """Pending list, Approve and Reject follow e-mail verification (client 2026-10-27)."""

    def setUp(self):
        super().setUp()
        self.admin = self.client_for(self.make_user("system_admin", email="admin@lspu.test"))
        self.verified = self.make_user(None, email="verified@lspu.test", is_active=False, email_verified_at=timezone.now())
        self.unverified = self.make_user(None, email="unverified@lspu.test", is_active=False)
        self.role = Role.objects.get(code="project_leader")

    def reject(self, user, client=None, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.admin).post(f"/api/admin/pending-users/{user.id}/reject/", data, format="json")

    def approve(self, user):
        with self.captureOnCommitCallbacks(execute=True):
            return self.admin.patch(f"/api/admin/pending-users/{user.id}/assign-role/", {"role_id": self.role.id},
                                    format="json")

    def test_pending_list_shows_only_verified_undecided_registrations(self):
        rejected = self.make_user(None, email="rejected@lspu.test", is_active=False, email_verified_at=timezone.now(),
                                  account_status="rejected")

        emails = [row["email"] for row in self.admin.get("/api/admin/pending-users/").data]

        self.assertEqual(emails, ["verified@lspu.test"])
        self.assertNotIn(rejected.email, [row["email"] for row in self.admin.get("/api/admin/users/").data])

    def test_unverified_registration_cannot_be_approved(self):
        response = self.approve(self.unverified)

        self.assertEqual(response.status_code, 400)
        self.unverified.refresh_from_db()
        self.assertFalse(self.unverified.is_active)
        self.brevo_post.assert_not_called()

    def test_reject_blocks_login_and_emails_the_reason_once(self):
        response = self.reject(self.verified, reason="Not an LSPU employee <b>")
        again = self.reject(self.verified)
        approve = self.approve(self.verified)
        login = APIClient().post("/api/auth/login/", {"email": "verified@lspu.test", "password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual((again.status_code, approve.status_code), (400, 400))
        self.verified.refresh_from_db()
        self.assertEqual((self.verified.account_status, self.verified.is_active), ("rejected", False))
        self.assertEqual(self.brevo_post.call_count, 1)
        mail = self.brevo_post.call_args.kwargs["json"]
        self.assertEqual(mail["to"][0]["email"], "verified@lspu.test")
        self.assertIn("Not an LSPU employee &lt;b&gt;", mail["htmlContent"])
        self.assertEqual(login.data["account_state"], ["rejected"])

    def test_confirmed_account_cannot_be_rejected(self):
        self.approve(self.verified)

        self.assertEqual(self.reject(self.verified).status_code, 400)
        self.verified.refresh_from_db()
        self.assertTrue(self.verified.is_active)

    def test_only_the_system_admin_rejects(self):
        response = self.reject(self.verified, client=self.client_for(self.make_user("crc_chair")))

        self.assertEqual(response.status_code, 403)
        self.verified.refresh_from_db()
        self.assertEqual(self.verified.account_status, "active")


class AdminConfirmationTests(RMISTestCase):
    def test_admin_assigning_a_role_activates_the_user_and_sends_confirmation(self):
        admin = self.make_user("system_admin")
        pending = self.make_user(None, email="pending@lspu.test", is_active=False, email_verified_at=timezone.now())
        role = Role.objects.get(code="project_leader")

        with self.captureOnCommitCallbacks(execute=True):  # the e-mail goes out only after the approval commits
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
        pending = self.make_user(None, email="pending@lspu.test", is_active=False, email_verified_at=timezone.now())
        self.client_for(admin).patch(
            f"/api/admin/pending-users/{pending.id}/assign-role/",
            {"role_id": Role.objects.get(code="project_leader").id}, format="json",
        )

        response = APIClient().post("/api/auth/login/", {"email": "pending@lspu.test", "password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200)

    def test_non_admin_cannot_assign_roles(self):
        leader = self.make_user("project_leader")
        pending = self.make_user(None, email="pending@lspu.test", is_active=False, email_verified_at=timezone.now())

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

    def google_request(self, **overrides):
        data = {
            "supabase_access_token": "x", "first_name": "Grace", "last_name": "Esmade", "gender": "female",
            "campus": "Los Baños", "college_unit": "CCS - College of Computer Studies", "mobile_number": "09181234567",
            "staff_id": "654321", "requested_role": Role.objects.get(code="project_staff").id,
        }
        data.update(overrides)
        return APIClient().post("/api/auth/google/request/", data, format="json")

    def test_request_creates_a_verified_pending_google_user_and_notifies_admins(self):
        CollegeUnit.objects.create(code="CCS", title="College of Computer Studies")
        admin = self.make_user("system_admin", email="admin@lspu.test")
        self.supabase_says(200, email="G.User@lspu.test")

        response = self.google_request()

        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="g.user@lspu.test")
        self.assertEqual(user.get_full_name(), "Grace Esmade")
        self.assertEqual(user.registration_method, "google")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.email_verified_at)  # Google proved the address; no verification e-mail
        self.assertEqual((user.staff_id, user.campus, user.requested_role.code), ("654321", "Los Baños", "project_staff"))
        recipients = [call.kwargs["json"]["to"][0]["email"] for call in self.brevo_post.call_args_list]
        self.assertEqual(recipients, ["admin@lspu.test"])
        pending = self.client_for(admin).get("/api/admin/pending-users/").data
        self.assertEqual([row["email"] for row in pending], ["g.user@lspu.test"])

    def test_request_needs_every_registration_field_but_no_password(self):
        CollegeUnit.objects.create(code="CCS", title="College of Computer Studies")
        self.supabase_says(200)

        no_name = self.google_request(last_name="")
        missing = {field: self.google_request(**{field: ""}) for field in
                   ("gender", "campus", "college_unit", "mobile_number", "staff_id", "requested_role")}
        admin_role = self.google_request(requested_role=Role.objects.get(code="system_admin").id)

        self.assertEqual(no_name.status_code, 400)
        for field, response in missing.items():
            with self.subTest(field=field):
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertIn("requested_role", admin_role.data)
        self.assertFalse(User.objects.filter(email="g.user@lspu.test").exists())

    def test_request_refuses_a_staff_id_already_registered(self):
        CollegeUnit.objects.create(code="CCS", title="College of Computer Studies")
        self.make_user("project_leader", staff_id="654321")
        self.supabase_says(200)

        response = self.google_request()

        self.assertEqual(response.status_code, 400)
        self.assertIn("staff_id", response.data)
        self.assertFalse(User.objects.filter(email="g.user@lspu.test").exists())


class AuditLogTests(RMISTestCase):
    def test_authenticated_writes_are_audit_logged(self):
        admin = self.make_user("system_admin")
        leader = self.make_user("project_leader")

        self.client_for(admin).patch(f"/api/admin/users/{leader.id}/scope/", {"campus": "Siniloan"}, format="json")

        log = AuditLog.objects.get()
        self.assertEqual((log.actor, log.method, log.status_code, log.error_detail), (admin, "PATCH", 200, ""))

    def test_a_rejected_write_keeps_the_validation_message(self):
        riuh = self.make_user("riuh")  # a registrant (the CRC Chair no longer registers, client 2026-10-24)

        self.client_for(riuh).post("/api/projects/", {"title": "No code"}, format="json")

        log = AuditLog.objects.get()
        self.assertEqual(log.status_code, 400)
        self.assertIn("project_code", log.error_detail)

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


class UserPickerTests(RMISTestCase):
    def test_admin_fills_in_an_accounts_name_office_and_position(self):
        user = self.make_user("project_staff")

        response = self.client_for(self.make_user("system_admin")).patch(
            f"/api/admin/users/{user.id}/profile/",
            {"first_name": "Grace", "last_name": "Esmade", "position": "Instructor I"}, format="json",
        )
        denied = self.client_for(self.make_user("crc_chair")).patch(
            f"/api/admin/users/{user.id}/profile/", {"first_name": "X"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["full_name"], response.data["position"]), ("Grace Esmade", "Instructor I"))
        self.assertEqual(denied.status_code, 403)

    def test_admin_sets_a_staff_id_and_clearing_it_leaves_no_clash(self):
        """The System Admin account predates Staff IDs and gets 000000 (Carl, 2026-10-27)."""
        admin = self.make_user("system_admin")
        client = self.client_for(admin)
        url = f"/api/admin/users/{admin.id}/profile/"

        response = client.patch(url, {"staff_id": "000000", "campus": "Sta. Cruz"}, format="json")
        bad = client.patch(url, {"staff_id": "0000", "college_unit": "Not a unit"}, format="json")
        other = self.make_user("project_staff")
        client.patch(url, {"staff_id": ""}, format="json")
        cleared = client.patch(f"/api/admin/users/{other.id}/profile/", {"staff_id": ""}, format="json")

        self.assertEqual((response.status_code, response.data["staff_id"], response.data["campus"]),
                         (200, "000000", "Sta. Cruz"))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(set(bad.data), {"staff_id", "college_unit"})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(list(User.objects.filter(pk__in=[admin.pk, other.pk]).values_list("staff_id", flat=True)),
                         [None, None])

    def test_people_picker_lists_every_active_account_with_a_display_name(self):
        """Client meeting 2026-10-01 (#6): the team picker offers any registered account, not only leaders."""
        leader = self.make_user("project_leader")
        named = self.make_user("project_staff", first_name="Dan Azriel", last_name="San Agustin")
        unnamed = self.make_user("finance_budget")

        response = self.client_for(leader).get("/api/users/by-role/")

        self.assertEqual(response.status_code, 200)
        names = {u["id"]: u["full_name"] for u in response.data}
        self.assertEqual(names[named.id], "Dan Azriel San Agustin")
        self.assertEqual(names[unnamed.id], unnamed.email)
