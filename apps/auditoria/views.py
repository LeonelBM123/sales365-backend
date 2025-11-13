from rest_framework import viewsets, permissions
from rest_framework.filters import OrderingFilter, SearchFilter
from .models import Bitacora
from .serializers import BitacoraSerializer
from config.pagination import CustomPageNumberPagination
from apps.users.utils import get_user_tienda

class IsAdminOrSuperAdmin(permissions.BasePermission):
    """Permiso para solo permitir acceso a usuarios con rol Admin o SuperAdmin."""
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if not hasattr(user, 'rol') or not user.rol:
            return False
        return user.rol.nombre in ['admin', 'superAdmin']

class BitacoraViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para la lectura de registros de auditoría (protegido)."""
    queryset = Bitacora.objects.all()
    serializer_class = BitacoraSerializer
    pagination_class = CustomPageNumberPagination
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]
    filter_backends = [OrderingFilter, SearchFilter]
    ordering_fields = ['timestamp', 'user__email', 'tienda__nombre', 'ip', 'accion']
    search_fields = ['accion', 'objeto', 'user__email', 'tienda__nombre', 'timestamp', 'ip']

    def get_queryset(self):
        user = self.request.user

        # El queryset base siempre debe optimizarse
        queryset = super().get_queryset().select_related('user__rol', 'user__profile', 'tienda')
        
        # El superAdmin ve todo
        if user.rol and user.rol.nombre == 'superAdmin':
            return queryset
        
        # Un admin solo ve los logs de su tienda
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(tienda=tienda_actual)
        
        # Si no es superAdmin y no tiene tienda, no ve nada
        return queryset.none()