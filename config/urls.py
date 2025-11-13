from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# --- Configuración base del esquema ---
schema_view = get_schema_view(
    openapi.Info(
        title="SmartSales365 API",
        default_version='v1',
        description="Sistema Inteligente de Gestión Comercial y Reportes Dinámicos",
        contact=openapi.Contact(email="maurogurpi@gmail.com"),
        license=openapi.License(name="Private License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

# --- Inyección manual del esquema de seguridad ---
def custom_schema_view(request, *args, **kwargs):
    """
    Función envolvente para agregar definición de seguridad al esquema generado.
    """
    schema = schema_view.with_ui('swagger', cache_timeout=0)(request, *args, **kwargs)
    if hasattr(schema, 'renderer_context'):
        schema.renderer_context['swagger_ui_settings'] = {
            "apisSorter": "alpha",
            "jsonEditor": False,
            "showRequestHeaders": True,
            "docExpansion": "none",
            "defaultModelsExpandDepth": -1,
        }
    return schema


urlpatterns = [
    path('admin/', admin.site.urls),

    # --- Documentación Swagger con header Authorization ---
    path(
        'swagger/',
        get_schema_view(
            openapi.Info(
                title="SmartSales365 API",
                default_version='v1',
                description="Sistema Inteligente de Gestión Comercial y Reportes Dinámicos",
                contact=openapi.Contact(email="maurogupri@gmail.com"),
                license=openapi.License(name="Private License"),
            ),
            public=True,
            permission_classes=(permissions.AllowAny,),
            authentication_classes=[],  # evita conflictos
        ).with_ui('swagger', cache_timeout=0),
        name='schema-swagger-ui',
    ),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # --- API principal ---
    path('api/v1/', include([
        path('usuarios/', include('apps.users.urls')),
        path('auditoria/', include('apps.auditoria.urls')),
        path('comercial/', include('apps.comercial.urls')),
        path('ventas/', include('apps.ventas.urls')),
        path('ia/', include('apps.predicciones.urls')),
        path('reportes/', include('apps.reportes.urls')),
        path('saas/', include('apps.saas.urls')),
    ])),
]

# --- Archivos estáticos y media ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
