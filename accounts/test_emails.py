from unittest import mock

import requests
from django.test import SimpleTestCase

from accounts.emails import send_brevo_email


def response(ok=True, status=201, body=None):
    resp = mock.Mock(ok=ok, status_code=status, text="error body")
    resp.json.side_effect = ValueError if body is None else None
    resp.json.return_value = body
    return resp


class SendBrevoEmailLogTests(SimpleTestCase):
    """Task 34: every e-mail Brevo accepts is logged with its messageId; failures stay errors and never raise."""

    @mock.patch("accounts.emails.requests.post")
    def test_accepted_logs_message_id(self, post):
        post.return_value = response(body={"messageId": "<abc@smtp-relay.mailin.fr>"})
        with self.assertLogs("accounts.emails", "INFO") as logs:
            self.assertIs(send_brevo_email("staff@lspu.edu.ph", "New Task Assigned — Survey", "<p>x</p>"), True)
        self.assertIn("staff@lspu.edu.ph", logs.output[0])
        self.assertIn("New Task Assigned — Survey", logs.output[0])
        self.assertIn("messageId=<abc@smtp-relay.mailin.fr>", logs.output[0])

    @mock.patch("accounts.emails.requests.post")
    def test_accepted_without_json_body(self, post):
        post.return_value = response(body=None)
        with self.assertLogs("accounts.emails", "INFO") as logs:
            self.assertIs(send_brevo_email("staff@lspu.edu.ph", "S", "<p>x</p>"), True)
        self.assertIn("messageId=None", logs.output[0])

    @mock.patch("accounts.emails.requests.post")
    def test_rejected_logs_error(self, post):
        post.return_value = response(ok=False, status=401)
        with self.assertLogs("accounts.emails", "INFO") as logs:
            self.assertIs(send_brevo_email("staff@lspu.edu.ph", "S", "<p>x</p>"), False)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "ERROR")
        self.assertIn("401", logs.output[0])

    @mock.patch("accounts.emails.requests.post", side_effect=requests.Timeout("timed out"))
    def test_network_error_returns_false(self, post):
        with self.assertLogs("accounts.emails", "ERROR") as logs:
            self.assertIs(send_brevo_email("staff@lspu.edu.ph", "S", "<p>x</p>"), False)
        self.assertIn("timed out", logs.output[0])
