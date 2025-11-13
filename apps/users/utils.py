def get_user_tienda(user):
    """
    Función auxiliar para obtener la tienda de un usuario a través de sus perfiles.
    Ahora vive en un lugar central y seguro.
    """
    if not user.is_authenticated:
        return None
        
    if hasattr(user, 'admin_profile') and user.admin_profile:
        return user.admin_profile.tienda
    if hasattr(user, 'vendedor_profile') and user.vendedor_profile:
        return user.vendedor_profile.tienda
    return None