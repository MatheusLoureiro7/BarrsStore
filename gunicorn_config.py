import logging
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 4
timeout = 120
max_requests = 1000
max_requests_jitter = 100


class _SentryBotFilter(logging.Filter):
    def filter(self, record):
        try:
            # record.args é o dict de atoms do gunicorn; 'a' = User-Agent
            return 'SentryUptimeBot' not in record.args.get('a', '')
        except (AttributeError, TypeError):
            return True


logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "no_sentry_bot": {
            "()": _SentryBotFilter,
        }
    },
    "handlers": {
        "access": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters": ["no_sentry_bot"],
        },
        "error": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "gunicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.error": {
            "handlers": ["error"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
