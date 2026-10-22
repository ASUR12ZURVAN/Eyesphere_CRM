import hashlib
import math
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


class RequestRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = settings.RATE_LIMITS.get(request.method)
        if limit is None:
            return self.get_response(request)

        now = time.time()
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        cutoff = now - window
        client_ip = request.META.get('REMOTE_ADDR', '')
        client_hash = hashlib.sha256(client_ip.encode('utf-8')).hexdigest()
        rate_group = 'write' if request.method in ('POST', 'PUT') else 'read'
        cache_key = f'lead-rate-limit:v1:{rate_group}:{client_hash}'

        timestamps = cache.get(cache_key, [])
        timestamps = [timestamp for timestamp in timestamps if timestamp > cutoff]

        if len(timestamps) >= limit:
            retry_after = max(1, math.ceil(timestamps[0] + window - now))
            response = HttpResponse(
                f'Too many {request.method} requests. Try again in {retry_after} seconds.',
                status=429,
            )
            response['Retry-After'] = str(retry_after)
            response['X-RateLimit-Limit'] = str(limit)
            response['X-RateLimit-Remaining'] = '0'
            return response

        timestamps.append(now)
        cache.set(cache_key, timestamps, timeout=window)

        response = self.get_response(request)
        response['X-RateLimit-Limit'] = str(limit)
        response['X-RateLimit-Remaining'] = str(limit - len(timestamps))
        return response
