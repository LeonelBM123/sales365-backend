from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'roles', views.RolViewSet, basename='rol')
router.register(r'clientes', views.ClienteViewSet, basename='cliente')
router.register(r'vendedores', views.VendedorViewSet, basename='vendedor')
router.register(r'administradores', views.AdministradorViewSet, basename='administrador')

urlpatterns = [
    path('', include(router.urls)),
]