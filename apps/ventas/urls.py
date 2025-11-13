from rest_framework.routers import DefaultRouter
from . import views
from django.urls import path

router = DefaultRouter()

# Registra tu nuevo ViewSet de Pagos
router.register(r'pagos', views.PagoViewSet, basename='pagos')
router.register(r'ventas', views.VentaViewSet, basename='ventas')
router.register(r'admin-ventas', views.VentaAdminViewSet, basename='admin-ventas')

urlpatterns = [
    path('pagos/webhook-stripe/', views.PagoViewSet.as_view({'post': 'stripe_webhook'}), name='stripe-webhook'),
]

urlpatterns += router.urls