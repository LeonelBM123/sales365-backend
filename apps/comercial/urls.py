from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()

router.register(r'marcas', views.MarcaViewSet, basename='marca')
router.register(r'categorias', views.CategoriaViewSet, basename='categoria')
router.register(r'productos', views.ProductoViewSet, basename='producto')
router.register(
    r'historial-precios', 
    views.LogPrecioProductoViewSet, 
    basename='log-precio-producto'
)
router.register(r'carritos', views.CarritoViewSet, basename='carrito')
router.register(r'fotos', views.FotoViewSet, basename='foto')

urlpatterns = [
    path('', include(router.urls)),
]
