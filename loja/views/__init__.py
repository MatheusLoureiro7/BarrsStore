# loja/views/__init__.py
# Re-exporta todos os simbolos dos submodulos para manter compatibilidade
# com loja/urls.py (from . import views; views.home, views.checkout, ...)
# e com management commands que importam diretamente de loja.views.

from .utils import *         # noqa: F401, F403
from .emails import *        # noqa: F401, F403
from .shipping import *      # noqa: F401, F403
from .payment import *       # noqa: F401, F403
from .cart import *          # noqa: F401, F403
from .store import *         # noqa: F401, F403
from .account import *       # noqa: F401, F403
from .dashboard import *     # noqa: F401, F403
