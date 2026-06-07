import os

from gunicorn.glogging import Logger

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 4
timeout = 120
max_requests = 1000
max_requests_jitter = 100

_SKIP_UAS = ('SentryUptimeBot',)


class FilteredLogger(Logger):
    def access(self, resp, req, environ, request_time):
        ua = environ.get('HTTP_USER_AGENT', '')
        if any(bot in ua for bot in _SKIP_UAS):
            return
        super().access(resp, req, environ, request_time)


logger_class = FilteredLogger
