from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .middleware import RequestRateLimitMiddleware


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'request-rate-limit-tests',
        }
    },
    RATE_LIMITS={'GET': 10, 'POST': 5, 'PUT': 5},
    RATE_LIMIT_WINDOW_SECONDS=60,
)
class RequestRateLimitMiddlewareTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.middleware = RequestRateLimitMiddleware(
            lambda request: HttpResponse('ok')
        )

    def make_request(self, method='GET', remote_addr='192.0.2.1'):
        return self.factory.generic(
            method,
            '/test/',
            REMOTE_ADDR=remote_addr,
        )

    def test_get_allows_ten_requests_then_returns_retry_after(self):
        for _ in range(10):
            response = self.middleware(self.make_request())
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-RateLimit-Remaining'], '0')

        response = self.middleware(self.make_request())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')
        self.assertEqual(response['X-RateLimit-Limit'], '10')

    def test_post_and_put_share_a_five_request_limit(self):
        methods = ('POST', 'PUT', 'POST', 'PUT', 'POST')
        for method in methods:
            self.assertEqual(
                self.middleware(self.make_request(method)).status_code,
                200,
            )

        self.assertEqual(self.middleware(self.make_request('PUT')).status_code, 429)
        self.assertEqual(self.middleware(self.make_request('POST')).status_code, 429)

    def test_expired_requests_do_not_count_in_the_rolling_window(self):
        now = [1_000.0]
        with patch('lead.middleware.time.time', side_effect=lambda: now[0]):
            for _ in range(10):
                self.assertEqual(self.middleware(self.make_request()).status_code, 200)

            now[0] += 60
            self.assertEqual(self.middleware(self.make_request()).status_code, 200)

    def test_limits_are_separate_by_client_ip_and_unconfigured_methods_are_exempt(self):
        for _ in range(10):
            self.middleware(self.make_request())

        self.assertEqual(
            self.middleware(self.make_request(remote_addr='192.0.2.2')).status_code,
            200,
        )
        self.assertEqual(
            self.middleware(self.make_request(method='DELETE')).status_code,
            200,
        )
