from django.apps import AppConfig


class LojaConfig(AppConfig):
    name = 'loja'
    _meta_config_logged = False

    def ready(self):
        import logging

        from django.conf import settings

        import loja.signals  # noqa: F401
        if not LojaConfig._meta_config_logged:
            logging.getLogger(__name__).info(
                '[META CONFIG] META_PIXEL_ID=%s META_TEST_EVENT_CODE=%s ACCESS_TOKEN_PRESENT=%s',
                getattr(settings, 'META_PIXEL_ID', '') or '',
                getattr(settings, 'META_TEST_EVENT_CODE', '') or '',
                bool(getattr(settings, 'META_ACCESS_TOKEN', '')),
            )
            LojaConfig._meta_config_logged = True
