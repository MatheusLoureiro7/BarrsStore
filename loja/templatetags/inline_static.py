from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils.safestring import mark_safe


register = template.Library()


@lru_cache(maxsize=64)
def _read_static_file_cached(path):
    found_path = finders.find(path)
    if not found_path:
        return ''
    return Path(found_path).read_text(encoding='utf-8')


def _read_static_file(path):
    if settings.DEBUG:
        found_path = finders.find(path)
        if not found_path:
            return ''
        return Path(found_path).read_text(encoding='utf-8')
    return _read_static_file_cached(path)


@register.simple_tag
def inline_static(path):
    return mark_safe(_read_static_file(path))


@register.filter
def first_word(value):
    """Retorna a primeira palavra do nome, capitalizada."""
    if not value:
        return ''
    return str(value).split()[0].capitalize()
