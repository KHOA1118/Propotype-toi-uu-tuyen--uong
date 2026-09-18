"""Public, non-secret deployment settings. No dotenv dependency required."""
import os
from urllib.parse import urlsplit


def api_base_url():
    value = os.getenv('API_BASE_URL', '').strip().rstrip('/')
    if value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('API_BASE_URL must be an HTTP(S) URL without credentials, query or fragment')
    return value


def allowed_origins():
    values = {s.strip().rstrip('/') for s in os.getenv('ALLOWED_ORIGINS', '').split(',') if s.strip()}
    for value in values:
        p = urlsplit(value)
        if p.scheme not in ('http','https') or not p.netloc or p.path or p.query or p.fragment or p.username or p.password:
            raise ValueError('ALLOWED_ORIGINS must contain explicit HTTP(S) origins')
    return values
