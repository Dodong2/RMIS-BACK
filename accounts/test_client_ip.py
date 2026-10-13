from django.test import RequestFactory, SimpleTestCase

from accounts.models import AuditLog
from accounts.testing import RMISTestCase
from config.client_ip import CloudflareClientIPMiddleware


class CloudflareClientIPMiddlewareTests(SimpleTestCase):
    def remote_addr(self, **headers):
        request = RequestFactory().get("/", REMOTE_ADDR="172.18.0.5", **headers)
        CloudflareClientIPMiddleware(lambda r: None)(request)
        return request.META["REMOTE_ADDR"]

    def test_uses_cf_connecting_ip(self):
        self.assertEqual(self.remote_addr(HTTP_CF_CONNECTING_IP="203.0.113.7"), "203.0.113.7")

    def test_ipv6(self):
        self.assertEqual(self.remote_addr(HTTP_CF_CONNECTING_IP="2001:db8::1"), "2001:db8::1")

    def test_no_header_keeps_remote_addr(self):
        self.assertEqual(self.remote_addr(), "172.18.0.5")

    def test_garbage_header_keeps_remote_addr(self):
        self.assertEqual(self.remote_addr(HTTP_CF_CONNECTING_IP="not-an-ip"), "172.18.0.5")

    def test_x_forwarded_for_is_ignored(self):
        self.assertEqual(self.remote_addr(HTTP_X_FORWARDED_FOR="6.6.6.6"), "172.18.0.5")


class AuditLogClientIPTests(RMISTestCase):
    def test_audit_log_records_real_client_ip(self):
        client = self.client_for(self.make_user("system_admin"))
        client.post("/api/admin/temporary-replacements/", {}, format="json", HTTP_CF_CONNECTING_IP="203.0.113.7")
        self.assertEqual(AuditLog.objects.latest("created_at").ip_address, "203.0.113.7")
