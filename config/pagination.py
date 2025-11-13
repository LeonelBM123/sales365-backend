from rest_framework.pagination import PageNumberPagination

class CustomPageNumberPagination(PageNumberPagination):
    # Número de elementos por página (20 tuplas)
    page_size = 20 
    # Permite al cliente cambiar el límite por query param (ej: ?page_size=10)
    page_size_query_param = 'page_size' 
    # Límite máximo para evitar que el cliente pida demasiados registros
    max_page_size = 100

class PublicProductPagination(PageNumberPagination):
    """
    Paginación para las vistas públicas de la tienda,
    con un tamaño de página por defecto de 8.
    """
    page_size = 8
    page_size_query_param = 'page_size' # Permite ?page_size=18
    max_page_size = 36 # Límite máximo