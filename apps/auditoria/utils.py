from django.conf import settings
from .models import Bitacora
from apps.users.utils import get_user_tienda

def get_client_ip(request):
    """Obtiene la IP del cliente desde el request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_actor_usuario_from_request(request):
    """Intenta obtener el usuario actor (objeto User) desde el request."""
    if hasattr(request, 'user') and request.user.is_authenticated:
        return request.user
    return None

def log_action(request, accion, objeto=None, usuario=None):
    """
    Registra una acción en la bitácora, asociándola a una tienda si corresponde.
    """
    try:
        ip = get_client_ip(request)
        if usuario is None:
            usuario = get_actor_usuario_from_request(request)

        tienda_actor = None
        if usuario:
            tienda_actor = get_user_tienda(usuario)

        Bitacora.objects.create(
            user=usuario,
            tienda=tienda_actor,
            accion=accion,
            ip=ip,
            objeto=objeto
        )
    except Exception as e:
        print(f"Error al registrar en bitácora: {e}")