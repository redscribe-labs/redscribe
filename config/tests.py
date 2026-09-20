import logging
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase, TestCase


class ProdDebugGuardTests(TestCase):
    def _run(self, env_overrides):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
            "DJANGO_SECRET_KEY": "test-secret-key-not-for-real-use",
            "REDSCRIBE_ROOT_KEY": "0" * 44,
            "POSTGRES_PASSWORD": "unused",
            **env_overrides,
        }
        return subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            env=env, capture_output=True, text=True, timeout=30,
        )

    def test_debug_true_without_override_refuses_to_boot(self):
        result = self._run({"DJANGO_DEBUG": "true"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REDSCRIBE_ALLOW_DEBUG_IN_PROD", result.stderr)

    def test_debug_true_with_explicit_override_boots(self):
        result = self._run({"DJANGO_DEBUG": "true", "REDSCRIBE_ALLOW_DEBUG_IN_PROD": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_debug_false_boots_normally(self):
        result = self._run({"DJANGO_DEBUG": "false"})
        self.assertEqual(result.returncode, 0, result.stderr)


class LoggingConfigTests(SimpleTestCase):
    def test_root_logger_has_a_handler(self):
        self.assertTrue(logging.getLogger().handlers)

    def test_app_logger_propagates_to_a_handled_root(self):
        logger = logging.getLogger("apps.notifications.services")
        with self.assertLogs("apps.notifications.services", level="ERROR") as captured:
            logger.error("smoke test error")
        self.assertIn("smoke test error", captured.output[0])

    def test_django_request_logger_is_configured_for_errors(self):
        logger = logging.getLogger("django.request")
        self.assertEqual(logger.level, logging.ERROR)
        self.assertTrue(logger.handlers)

    def test_django_log_level_is_configurable_via_env(self):
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev", "DJANGO_LOG_LEVEL": "WARNING"}
        result = subprocess.run(
            [sys.executable, "-c", (
                "import django; django.setup(); from django.conf import settings; "
                "print(settings.LOGGING['root']['level'])"
            )],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "WARNING", result.stderr)


class HealthCheckTests(TestCase):
    def test_health_returns_200_ok(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_does_not_require_authentication(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 200)
