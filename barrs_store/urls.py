from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from loja import views as loja_views

handler404 = loja_views.pagina_404

urlpatterns = [
    path('painel/', admin.site.urls),
    path('', include('loja.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
