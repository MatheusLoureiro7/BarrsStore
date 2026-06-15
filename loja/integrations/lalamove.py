import hashlib
import hmac as hmac_lib
import json
import logging
import time

import requests as http_requests
from django.core.cache import cache

logger = logging.getLogger(__name__)


def is_sao_paulo_cep(cep: str) -> bool:
    cep = cep.replace('-', '').replace(' ', '')
    if len(cep) != 8 or not cep.isdigit():
        return False
    n = int(cep)
    return (1_000_000 <= n <= 5_999_999) or (8_000_000 <= n <= 8_499_999)
