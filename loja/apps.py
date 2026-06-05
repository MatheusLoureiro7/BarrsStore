from django.apps import AppConfig


class LojaConfig(AppConfig):
    name = 'loja'

    def ready(self):
        import loja.signals  # noqa: F401
