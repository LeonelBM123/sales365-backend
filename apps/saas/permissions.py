from rest_framework.permissions import BasePermission
from apps.users.utils import get_user_tienda 

class IsTenantActive(BasePermission):
    """
    Permiso personalizado que verifica el acceso basado en el rol y 
    el estado de la suscripción de la tienda.
    
    - SuperAdmin: Siempre tiene acceso.
    - Cliente: Siempre tiene acceso (solo requiere autenticación).
    - Admin / Vendedor: Requieren una tienda asociada con estado 'ACTIVO' o 'PRUEBA'.
    """
    
    # Mensaje por defecto si falla la comprobación de la tienda
    message = "La suscripción de tu tienda no está activa o no tienes permisos."

    def has_permission(self, request, view):
        user = request.user

        # 1. IsAuthenticated ya debería haber corrido, pero por si acaso.
        if not user or not user.is_authenticated:
            return False

        # 2. Obtener el rol del usuario de forma segura
        rol_nombre = user.rol.nombre if user.rol else None

        # 3. ROL: SuperAdmin -> Acceso Total
        # Pasa sin importar nada más.
        if rol_nombre == 'superAdmin':
            return True

        # 4. ROL: Cliente -> Acceso Permitido
        # El cliente solo necesita estar logueado. No tiene tienda
        # que comprobar.
        if rol_nombre == 'Cliente':
            return True

        # 5. ROL: Admin o Vendedor -> Comprobación de Tienda
        # Estos roles SÍ dependen del estado de la tienda.
        if rol_nombre in ['admin', 'vendedor']:
            
            tienda = get_user_tienda(user)

            # 5a. Si es Admin/Vendedor pero no tiene tienda
            if not tienda:
                self.message = f"Tu usuario con rol '{rol_nombre}' no está asociado a ninguna tienda."
                return False #  Denegado

            # 5b. Si tiene tienda, comprobar su estado
            if tienda.estado in ['ACTIVO', 'PRUEBA']:
                return True #  Permitido
            
            # 5c. Si la tienda está INACTIVA, CANCELADA, etc.
            self.message = "La suscripción de tu tienda no está activa. Por favor, contacta a soporte."
            return False #  Denegado

        # 6. Otros roles (o sin rol)
        # Si el usuario no es SuperAdmin, Cliente, Admin, ni Vendedor,
        # se le niega el acceso por defecto.
        self.message = "No tienes un rol válido para acceder a este recurso."
        return False