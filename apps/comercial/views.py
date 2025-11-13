from rest_framework import viewsets, status, permissions, serializers, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F, Q, Count
from django.db import transaction
from decimal import Decimal
from .models import (
    Marca, Categoria, LogPrecioProducto, Producto, Foto, 
    Carrito, Detalle_Carrito
)
from .serializers import (
    MarcaSerializer, CategoriaSerializer, LogPrecioProductoSerializer,
    ProductoSerializer, FotoSerializer, CarritoSerializer,
    ProductoPublicSerializer
)
from apps.auditoria.utils import log_action
from config.pagination import CustomPageNumberPagination, PublicProductPagination
from apps.users.utils import get_user_tienda 
from apps.saas.models import Tienda

class IsSuperAdmin(permissions.BasePermission):
    """ Permite el acceso solo a usuarios con el rol de superAdmin. """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.rol and request.user.rol.nombre == 'superAdmin'

class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Permite acceso de LECTURA (GET) a cualquier usuario autenticado,
    pero solo permite ESCRITURA (POST, PUT, DELETE) a Admins o SuperAdmins.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.rol and request.user.rol.nombre in ['admin', 'superAdmin']

# --- ViewSet Base Multi-Tenancy ---

class TenantAwareViewSet(viewsets.ModelViewSet):
    """
    Un ViewSet base que filtra el queryset para la tienda del usuario actual
    y asigna automáticamente la tienda al crear nuevos objetos.
    El superAdmin puede ver todos los datos.
    """
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    def get_queryset(self):
        """ Filtra el queryset por la tienda del usuario. """
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.rol and user.rol.nombre == 'superAdmin':
            return queryset # SuperAdmin ve todo
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return queryset.filter(tienda=tienda_actual)
        
        return queryset.none() # No es SuperAdmin y no tiene tienda

    def get_serializer_context(self):
        """ Inyecta la tienda y el request en el serializer. """
        context = super().get_serializer_context()
        context['request'] = self.request
        
        if self.request.user.is_authenticated:
            context['usuario'] = self.request.user
            if not (self.request.user.rol and self.request.user.rol.nombre == 'superAdmin'):
                context['tienda'] = get_user_tienda(self.request.user)
        
        return context

    def perform_create(self, serializer):
        """ Asigna automáticamente la tienda al crear un objeto. """
        user = self.request.user
        
        if user.rol and user.rol.nombre == 'superAdmin':
            serializer.save() 
        else:
            tienda_actual = get_user_tienda(user)
            if not tienda_actual:
                raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
            
            # Pasa el 'usuario' al serializer para el log de auditoría
            serializer.save(tienda=tienda_actual, usuario=user)
    
    def perform_update(self, serializer):
        # Pasa el 'usuario' al serializer para el log de auditoría
        serializer.save(usuario=self.request.user)


# --- ViewSets de Catálogo ---
class MarcaViewSet(TenantAwareViewSet):
    """ API endpoint para Marcas, filtrado por tienda. """
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'estado']

    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        marca = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó Marca", f"Marca: {marca.nombre} (ID: {marca.id})", user)

    def perform_update(self, serializer):
        original_estado = serializer.instance.estado
        marca = serializer.save(usuario=self.request.user)
        
        # Lógica de Log para "Activar" / "Desactivar"
        accion = "Actualizó Marca"
        if 'estado' in serializer.validated_data:
            if original_estado != marca.estado:
                accion = "Activó Marca" if marca.estado else "Desactivó Marca"
                
        log_action(self.request, accion, f"Marca: {marca.nombre} (ID: {marca.id})", self.request.user)

    def perform_destroy(self, instance):
        """
        Implementa el BORRADO LÓGICO.
        En lugar de borrar, cambia el estado a 'False'.
        """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado: # Solo desactiva si estaba activa
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Marca (vía Delete)", f"Marca: {nombre} (ID: {id_instancia})", self.request.user)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[permissions.AllowAny],
        url_path='public-con-productos'
    )
    def public_con_productos(self, request):
        """
        Retorna un listado de marcas activas que tienen al menos 1 producto activo,
        filtradas por tienda.
        
        Query Params:
        - tienda (requerido): ID de la tienda.
        - categoria_id (opcional): Filtra marcas que tengan productos en esta categoría.
        """
        tienda_id = request.query_params.get('tienda')
        if not tienda_id:
            return Response(
                {"error": "El parámetro 'tienda' es requerido."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Queryset base: Marcas activas de la tienda
        queryset = Marca.objects.filter(tienda_id=tienda_id, estado=True)
        
        # Filtro de anotación base
        filtro_productos = Q(producto__estado=True, producto__tienda_id=tienda_id)

        # Si se especifica una categoría, se añade al filtro de productos
        categoria_id = request.query_params.get('categoria_id')
        if categoria_id:
            try:
                # Nos aseguramos que la categoría también pertenezca a la tienda
                Categoria.objects.get(pk=categoria_id, tienda_id=tienda_id)
                filtro_productos &= Q(producto__categorias__id=categoria_id)
            except Categoria.DoesNotExist:
                return Response(
                    {"error": "Categoría no válida para esta tienda."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Anotamos, filtramos por las que tienen productos, y aseguramos unicidad
        queryset = queryset.annotate(
            total_productos=Count('producto', filter=filtro_productos)
        ).filter(total_productos__gt=0).distinct()

        # Usamos el serializer estándar
        serializer = self.get_serializer(queryset, many=True)
        
        # Añadimos el contador al serializer data
        data = serializer.data
        for i, marca in enumerate(queryset):
            data[i]['total_productos'] = marca.total_productos
            
        return Response(data)

class CategoriaViewSet(TenantAwareViewSet):
    """ API endpoint para Categorías, filtrado por tienda. """
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'estado']

    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        categoria = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó Categoría", f"Categoría: {categoria.nombre} (ID: {categoria.id})", user)

    def perform_update(self, serializer):
        original_estado = serializer.instance.estado
        
        categoria = serializer.save(usuario=self.request.user)
        
        accion = "Actualizó Categoría"
        if 'estado' in serializer.validated_data:
            if original_estado != categoria.estado:
                accion = "Activó Categoría" if categoria.estado else "Desactivó Categoría"
                
        log_action(self.request, accion, f"Categoría: {categoria.nombre} (ID: {categoria.id})", self.request.user)

    def perform_destroy(self, instance):
        """ Implementa el BORRADO LÓGICO. """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado:
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Categoría (vía Delete)", f"Categoría: {nombre} (ID: {id_instancia})", self.request.user)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[permissions.AllowAny],
        url_path='public-con-productos'
    )
    def public_con_productos(self, request):
        """
        Retorna un listado de categorías activas que tienen al menos 1 producto activo,
        filtradas por tienda.
        
        Query Params:
        - tienda (requerido): ID de la tienda.
        """
        tienda_id = request.query_params.get('tienda')
        if not tienda_id:
            return Response(
                {"error": "El parámetro 'tienda' es requerido."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Filtramos por tienda, estado, y anotamos con productos activos
        queryset = Categoria.objects.filter(
            tienda_id=tienda_id, estado=True
        ).annotate(
            total_productos=Count('productos', filter=Q(productos__estado=True, productos__tienda_id=tienda_id))
        ).filter(total_productos__gt=0) # Solo las que tienen productos
        
        serializer = self.get_serializer(queryset, many=True)
        
        # Añadimos el contador al serializer data
        data = serializer.data
        for i, categoria in enumerate(queryset):
            data[i]['total_productos'] = categoria.total_productos
        
        return Response(data)



class LogPrecioProductoViewSet(TenantAwareViewSet):
    """ API endpoint de solo lectura para el historial de precios. """
    queryset = LogPrecioProducto.objects.select_related('producto', 'usuario_que_modifico').all()
    serializer_class = LogPrecioProductoSerializer
    http_method_names = ['get', 'head', 'options'] # Solo lectura
    filterset_fields = ['producto']
    ordering_fields = ['-fecha_cambio']

class FotoViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    ViewSet simple para permitir BORRAR fotos.
    El frontend lo usará para gestionar las fotos eliminadas.
    """
    queryset = Foto.objects.all()
    serializer_class = FotoSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly] 

    def get_queryset(self):
        """ El usuario solo puede borrar fotos de su propia tienda """
        user = self.request.user
        if user.rol and user.rol.nombre == 'superAdmin':
            return Foto.objects.all()
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return Foto.objects.filter(producto__tienda=tienda_actual)
        
        return Foto.objects.none()

class ProductoViewSet(TenantAwareViewSet):
    """ API endpoint para Productos. """
    queryset = Producto.objects.select_related('marca', 'tienda').prefetch_related('categorias', 'fotos').all()
    serializer_class = ProductoSerializer
    
    # Filtros
    search_fields = ['nombre', 'descripcion', 'codigo_referencia']
    ordering_fields = ['nombre', 'precio', 'stock', 'estado']
    filterset_fields = {
        'tienda': ['exact'],
        'marca': ['exact'],
        'categorias': ['exact'],
        'estado': ['exact'],
        'precio': ['gte', 'lte'],
    }

    def perform_create(self, serializer):
        user = self.request.user
        tienda_actual = get_user_tienda(user)
        
        if user.rol and user.rol.nombre == 'superAdmin':
             tienda_id = self.request.data.get('tienda_id')
             if not tienda_id:
                 raise serializers.ValidationError("SuperAdmin debe proveer 'tienda_id'.")
             tienda_actual = Tienda.objects.get(pk=tienda_id)
        
        if not tienda_actual:
            raise serializers.ValidationError("Tu usuario no está asociado a ninguna tienda.")
        
        producto = serializer.save(tienda=tienda_actual, usuario=user)
        log_action(self.request, "Creó producto", f"Producto: {producto.nombre}", user)

    def perform_update(self, serializer):
        original_estado = serializer.instance.estado
        producto = serializer.save() 
        
        accion = "Actualizó Producto"
        if 'estado' in serializer.validated_data:
            if original_estado != producto.estado:
                accion = "Activó Producto" if producto.estado else "Desactivó Producto"
        
        log_action(self.request, accion, f"Producto: {producto.nombre} (ID: {producto.id})", self.request.user)

    def perform_destroy(self, instance):
        """ Implementa el BORRADO LÓGICO para Productos. """
        nombre = instance.nombre
        id_instancia = instance.id
        
        if instance.estado:
            instance.estado = False
            instance.save()
            log_action(self.request, "Desactivó Producto (vía Delete)", f"Producto: {nombre} (ID: {id_instancia})", self.request.user)

    @action(
        detail=True, 
        methods=['post'], 
        permission_classes=[IsAuthenticated, IsAdminOrReadOnly],
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload-foto'
    )
    def upload_foto(self, request, pk=None):
        """ Sube o actualiza una foto para un producto. """
        producto = self.get_object()
        
        if producto.fotos.count() >= 5:
            return Response(
                {"error": "Límite de 5 fotos alcanzado para este producto."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if 'foto' not in request.FILES:
            return Response({"error": "No se proporcionó ninguna imagen."}, status=status.HTTP_400_BAD_REQUEST)

        data = {'producto': producto.pk, 'foto': request.FILES['foto']}
        
        if 'principal' in request.data:
            data['principal'] = request.data.get('principal')

        serializer = FotoSerializer(data=data, context=self.get_serializer_context())
        
        if serializer.is_valid():
            if serializer.validated_data.get('principal', False):
                producto.fotos.update(principal=False)
            
            foto = serializer.save()
            log_action(request, "Subió foto de producto", f"Producto: {producto.nombre}", request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(
        detail=True, 
        methods=['post'], 
        permission_classes=[IsAuthenticated, IsAdminOrReadOnly],
        url_path='set-principal-foto'
    )
    def set_principal_foto(self, request, pk=None):
        """
        Establece una foto EXISTENTE como la principal.
        Espera un JSON: { "foto_id": "ID_DE_LA_FOTO" }
        """
        producto = self.get_object()
        foto_id = request.data.get('foto_id')

        if not foto_id:
            return Response(
                {"error": "'foto_id' es requerido."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Desmarca todas las fotos de este producto
            producto.fotos.update(principal=False)
            
            # Marca la foto seleccionada como principal
            foto = Foto.objects.get(pk=foto_id, producto=producto)
            foto.principal = True
            foto.save()
            
            return Response(
                {"success": f"Foto {foto_id} es ahora la principal."}, 
                status=status.HTTP_200_OK
            )
            
        except Foto.DoesNotExist:
            return Response(
                {"error": "Foto no encontrada o no pertenece a este producto."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated],
        url_path='destacados'
    )
    def destacados(self, request):
        """
        Endpoint para obtener productos destacados.
        Retorna productos con stock > 0, ordenados por fecha de creación (más recientes primero).
        Query params opcionales:
        - limit: número de productos a retornar (default: 10)
        """
        limit = int(request.query_params.get('limit', 10))
        
        queryset = self.get_queryset().filter(
            estado=True,
            stock__gt=0
        ).order_by('-id')[:limit]
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated],
        url_path='ofertas'
    )
    def ofertas(self, request):
        """
        Endpoint para obtener productos en oferta.
        Retorna productos con stock bajo (stock < 10) como 'ofertas'.
        Query params opcionales:
        - limit: número de productos a retornar (default: 10)
        """
        limit = int(request.query_params.get('limit', 10))
        
        queryset = self.get_queryset().filter(
            estado=True,
            stock__lt=10,
            stock__gt=0
        ).order_by('stock')[:limit]
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[permissions.AllowAny], # Abierto al público
        url_path='public-list'
        # ¡OJO! No podemos poner pagination_class aquí en el decorador
    )
    def public_list(self, request):
        """
        Retorna la lista PÚBLICA y paginada de productos para una tienda.
        """
        
        tienda_id = request.query_params.get('tienda')
        if not tienda_id:
            return Response(
                {"error": "El parámetro 'tienda' es requerido."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = self.queryset.filter(
            tienda_id=tienda_id, 
            estado=True
        )

        # Aplicamos los filtros de búsqueda, ordenamiento y filterset
        filtered_queryset = self.filter_queryset(queryset)
        
        # --- 
        # --- APLICACIÓN MANUAL DE LA PAGINACIÓN ---
        # ---
        
        # 1. Instanciamos el paginador que creamos
        paginator = PublicProductPagination()
        
        # 2. Paginar el queryset
        page = paginator.paginate_queryset(filtered_queryset, request, view=self)
        
        # 3. Esta lógica ahora usará nuestro paginador (page_size=9)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context=self.get_serializer_context())
            # 4. Usamos el 'get_paginated_response' del *nuevo* paginador
            return paginator.get_paginated_response(serializer.data)

        # Fallback (no debería pasar si todo está bien)
        serializer = self.get_serializer(filtered_queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)
    
    @action(
        detail=True,
        methods=['get'],
        permission_classes=[permissions.AllowAny],
        url_path='public-detail'
    )
    def public_detail(self, request, pk=None):
        """
        Retorna los detalles PÚBLICOS de un producto específico.
        Solo muestra productos activos (estado=True).
        """
        try:
            # Obtener el producto por ID, pero solo si está activo
            producto = Producto.objects.select_related('marca', 'tienda').prefetch_related('categorias', 'fotos').filter(
                pk=pk,
                estado=True
            ).first()
            
            if not producto:
                return Response(
                    {"error": "Producto no encontrado o no disponible."}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Usar el serializer público
            serializer = ProductoPublicSerializer(producto, context={'request': request})
            return Response(serializer.data)
            
        except Exception as e:
            print(f"Error en public_detail: {str(e)}")  # Mantén esto por si hay otros errores
            return Response(
                {"error": "Error interno del servidor"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
# --- ViewSets de Carrito ---
class CarritoViewSet(viewsets.GenericViewSet):
    """
    API endpoint para gestionar la *confirmación* del carrito de compras.
    """
    queryset = Carrito.objects.prefetch_related('items__producto__fotos').all()
    serializer_class = CarritoSerializer
    permission_classes = [IsAuthenticated] # Solo usuarios logueados pueden confirmar

    @action(detail=False, methods=['post'], url_path='confirmar-pedido')
    def confirmar_pedido(self, request):
        """
        Recibe un carrito completo desde el frontend (localStorage)
        y lo guarda en la base de datos como un Carrito/Pedido.

        Espera un JSON:
        {
            "tienda_id": 1,
            "items": [
                { "producto_id": 10, "cantidad": 2 },
                { "producto_id": 12, "cantidad": 1 }
            ]
        }
        """
        
        # 1. Obtener el perfil de cliente del usuario
        try:
            cliente = request.user.cliente_profile
        except Cliente.DoesNotExist:
            return Response(
                {"error": "Tu cuenta de usuario no es un cliente válido."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Validar datos de entrada
        tienda_id = request.data.get('tienda_id')
        items_data = request.data.get('items', [])

        if not tienda_id:
            return Response(
                {"error": "El campo 'tienda_id' es requerido."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not items_data:
            return Response(
                {"error": "El carrito está vacío. No se enviaron 'items'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            tienda = Tienda.objects.get(pk=tienda_id)
        except Tienda.DoesNotExist:
            return Response(
                {"error": "Tienda no encontrada."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3. Iniciar transacción atómica
        try:
            with transaction.atomic():
                
                # 4. Crear el Carrito (Pedido) principal
                nuevo_carrito = Carrito.objects.create(
                    cliente=cliente,
                    tienda=tienda,
                    total=Decimal('0.00') # <--- CAMBIO AQUÍ: Iniciar total en 0
                )
                
                detalles_a_crear = []
                productos_a_actualizar = []
                total_pedido = Decimal('0.00') # <--- CAMBIO AQUÍ: Inicializar total

                # 5. Iterar sobre los items para validar stock y preparar la creación
                for item_data in items_data:
                    producto_id = item_data.get('producto_id')
                    cantidad_str = item_data.get('cantidad')

                    # --- Validación de cantidad ---
                    if not producto_id or not cantidad_str:
                         raise serializers.ValidationError(f"Item inválido en el carrito (datos faltantes).")
                    try:
                        cantidad = int(cantidad_str)
                        if cantidad <= 0: raise ValueError()
                    except (ValueError, TypeError):
                         raise serializers.ValidationError(f"Cantidad inválida para el producto ID {producto_id}.")

                    # --- Validación de Producto y Stock ---
                    try:
                        producto = Producto.objects.select_for_update().get(
                            pk=producto_id, 
                            tienda=tienda, 
                            estado=True
                        )
                    except Producto.DoesNotExist:
                        raise serializers.ValidationError(f"El producto con ID {producto_id} no se encuentra o no está disponible.")

                    if producto.stock < cantidad:
                        raise serializers.ValidationError(
                            f"Stock insuficiente para '{producto.nombre}'. "
                            f"Disponible: {producto.stock}, Solicitado: {cantidad}"
                        )
                    
                    # --- Lógica de Pedido ---
                    producto.stock -= cantidad
                    productos_a_actualizar.append(producto)

                    # <--- CAMBIO AQUÍ: Capturar precio y calcular total ---
                    precio_en_compra = producto.precio 
                    total_pedido += (precio_en_compra * cantidad)

                    # Preparar el Detalle_Carrito
                    detalles_a_crear.append(
                        Detalle_Carrito(
                            carrito=nuevo_carrito,
                            producto=producto,
                            cantidad=cantidad,
                            precio_unitario=precio_en_compra # <--- CAMBIO AQUÍ: Guardar precio
                        )
                    )

                # 6. Guardar todo en la Base de Datos
                Detalle_Carrito.objects.bulk_create(detalles_a_crear)
                Producto.objects.bulk_update(productos_a_actualizar, ['stock'])
                
                # <--- CAMBIO AQUÍ: Guardar el total final en el Carrito ---
                nuevo_carrito.total = total_pedido 
                nuevo_carrito.save(update_fields=['total'])

        # 7. Manejar errores de validación (ej. Stock)
        except serializers.ValidationError as e:
            return Response(
                {"error": e.detail[0] if isinstance(e.detail, list) else str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 8. Devolver el pedido recién creado
        nuevo_carrito.refresh_from_db()
        serializer = self.get_serializer(nuevo_carrito)
        return Response(serializer.data, status=status.HTTP_201_CREATED)