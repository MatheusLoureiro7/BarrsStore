from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from loja import views as loja_views
from django.views.generic.base import RedirectView

handler404 = loja_views.pagina_404

urlpatterns = [
    path('painel/', admin.site.urls),
    path('favicon.ico', RedirectView.as_view(
        url='https://res.cloudinary.com/dsw5fkmwp/image/upload/q_auto/f_auto/v1777401449/ChatGPT_Image_28_de_abr._de_2026_15_37_19_ovzkth.png',
        permanent=True
    )),
    path('', include('loja.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)