"""Rate limits (config/settings.py DEFAULT_THROTTLE_RATES). Anonymous requests are counted per client IP, which
config/client_ip.py takes from CF-Connecting-IP; logged-in requests per user."""
from rest_framework.test import APIClient

from accounts.testing import PASSWORD, RMISTestCase


class ThrottlingTests(RMISTestCase):
    def login(self, ip="203.0.113.1"):
        return APIClient().post(
            "/api/auth/login/", {"email": "nobody@lspu.test", "password": PASSWORD}, format="json",
            HTTP_CF_CONNECTING_IP=ip,
        )

    def test_sixth_login_in_a_minute_from_one_ip_is_throttled(self):
        for _ in range(5):
            self.assertEqual(self.login().status_code, 400)  # wrong credentials, still counted
        self.assertEqual(self.login().status_code, 429)

    def test_login_limit_is_per_cloudflare_client_ip(self):
        for _ in range(5):
            self.login(ip="203.0.113.1")
        self.assertEqual(self.login(ip="203.0.113.1").status_code, 429)
        self.assertEqual(self.login(ip="198.51.100.7").status_code, 400)

    def test_fourth_registration_in_an_hour_from_one_ip_is_throttled(self):
        for i in range(3):
            response = APIClient().post("/api/auth/register/", {
                "email": f"new{i}@lspu.test", "password": PASSWORD, "password2": PASSWORD,
                "first_name": "New", "last_name": "Researcher",
            }, format="json", HTTP_CF_CONNECTING_IP="203.0.113.1")
            self.assertNotEqual(response.status_code, 429)
        response = APIClient().post("/api/auth/register/", {}, format="json", HTTP_CF_CONNECTING_IP="203.0.113.1")
        self.assertEqual(response.status_code, 429)

    def test_token_refresh_is_throttled_after_30_a_minute(self):
        for _ in range(30):
            response = APIClient().post("/api/auth/token/refresh/", {"refresh": "garbage"}, format="json")
            self.assertEqual(response.status_code, 401)
        response = APIClient().post("/api/auth/token/refresh/", {"refresh": "garbage"}, format="json")
        self.assertEqual(response.status_code, 429)

    def test_heavy_compute_is_throttled_per_user(self):
        url = "/api/decision-support/recommendation-runs/999999/sensitivity/"
        first, second = self.client_for(self.make_user("system_admin")), self.client_for(self.make_user("system_admin"))
        for _ in range(10):
            self.assertEqual(first.get(url, {"criterion": 1}).status_code, 404)
        self.assertEqual(first.get(url, {"criterion": 1}).status_code, 429)
        self.assertEqual(second.get(url, {"criterion": 1}).status_code, 404)
