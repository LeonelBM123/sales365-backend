from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'planes', PlanSuscripcionViewSet, basename='plan')
router.register(r'tiendas', TiendaViewSet, basename='tienda')
router.register(r'pagos', PagoSuscripcionViewSet, basename='pago')
router.register(r'public/tiendas', PublicTiendaViewSet, basename='tiendas-publicas')

urlpatterns = [
    path('', include(router.urls)),
    
    # --- RUTA PARA REGISTRO DE PRUEBA GRATUITA ---
    path('registro/directo/', registro_directo_prueba, name='registro-directo-prueba'),
    
    # --- RUTAS PARA EL FLUJO DE PAGO CON STRIPE ---
    path('stripe/crear-sesion/', crear_sesion_pago_stripe, name='stripe-crear-sesion'),
    path('stripe/confirmar/', confirmar_registro_pago, name='stripe-confirmar-pago'),

    
]
