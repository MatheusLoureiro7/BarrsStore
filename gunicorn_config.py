import logging
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 4
timeout = 120
max_requests = 1000
max_requests_jitter = 100
accesslog = '-'

_SKIP_UAS = (
    'SentryUptimeBot',
    'facebookexternalhit',
    'meta-externalads',
    'Claude-SearchBot',
)


class _BotFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not any(bot in msg for bot in _SKIP_UAS)


logconfig_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'no_bots': {'()': _BotFilter},
    },
    'handlers': {
        'access': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'filters': ['no_bots'],
        },
        'error': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
        },
    },
    'loggers': {
        'gunicorn.access': {
            'handlers': ['access'],
            'level': 'INFO',
            'propagate': False,
        },
        'gunicorn.error': {
            'handlers': ['error'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['error'],
        'level': 'WARNING',
    },
}
