from rest_framework.authentication import TokenAuthentication
from rest_framework import exceptions
from django.utils import timezone
from datetime import timedelta

class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Una clase de autenticación que extiende la de DRF para que los tokens
    expiren después de un período de inactividad.
    """
    def authenticate_credentials(self, key):
        # Primero, usamos el método original para obtener el usuario y el token
        # Esto valida que el token exista y el usuario esté activo.
        try:
            user, token = super().authenticate_credentials(key)
        except exceptions.AuthenticationFailed:
            raise

        # Ahora, añadimos nuestra lógica de expiración
        # Comprobamos si el token ha expirado
        if (timezone.now() - token.created) > timedelta(minutes=15):
            # Si ha expirado, borramos el token y lanzamos un error
            token.delete()
            raise exceptions.AuthenticationFailed('El token ha expirado por inactividad. Por favor, inicie sesión de nuevo.')

        # Si el token es válido, actualizamos su fecha de creación para reiniciar el contador
        # Esto mantiene la sesión activa mientras el usuario interactúa con la API
        token.created = timezone.now()
        token.save()

        return (user, token)