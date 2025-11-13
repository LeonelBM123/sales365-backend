from django.shortcuts import render
import stripe
import json
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from django.http import HttpResponse

from rest_framework import viewsets, status, permissions, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter

# Modelos de esta app (ventas)
from .models import Venta, Detalle_Venta, Pago, Envio

# Modelos de otras apps (users, comercial, saas)
from apps.users.views import TenantAwareViewSet
from apps.users.models import Cliente
from apps.comercial.models import Producto, Carrito, Detalle_Carrito
from apps.saas.models import Tienda, TiendaCliente
from apps.auditoria.utils import log_action

from .serializers import VentaSerializer
from config.pagination import CustomPageNumberPagination

# --- Configuración de Stripe ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# --- Lógica de Envío ---
def calcular_costo_envio(subtotal):
    """
    Calcula el costo de envío basado en el subtotal.
    Debe ser idéntico a la lógica del frontend.
    """
    if subtotal == 0:
        porcentaje_envio = 0
    elif subtotal < 100:   # Menos de 100 bs
        porcentaje_envio = 15
    elif subtotal < 500:   # Entre 100 y 499.99 bs
        porcentaje_envio = 10
    elif subtotal < 1000:  # Entre 500 y 999.99 bs
        porcentaje_envio = 5
    else:                  # 1000 bs o más
        porcentaje_envio = 0
    
    costo_envio = (subtotal * (Decimal(str(porcentaje_envio)) / Decimal('100.0')))
    return costo_envio.quantize(Decimal('0.01'))


# --- ViewSet para Pagos con Stripe ---

class PagoViewSet(viewsets.GenericViewSet):
    """
    ViewSet para manejar la creación y verificación
    de sesiones de pago con Stripe.
    """
    # Este permiso se aplica a todo el ViewSet por defecto
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='crear-sesion-checkout', 
            permission_classes=[permissions.IsAuthenticated])
    def crear_sesion_checkout(self, request):
        """
        Recibe los items del carrito y una dirección, recalcula el total 
        y crea una sesión de pago de Stripe Checkout.
        """
        
        try:
            cliente = request.user.cliente_profile
        except Cliente.DoesNotExist:
            return Response(
                {"error": "Tu cuenta de usuario no es un cliente válido."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        tienda_id = request.data.get('tienda_id')
        items_data = request.data.get('items', [])
        direccion_entrega = request.data.get('direccion_entrega')
        
        if not tienda_id or not items_data:
            return Response(
                {"error": "Se requiere tienda_id y al menos un item."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not direccion_entrega:
                 return Response(
                {"error": "Se requiere una 'direccion_entrega' para el envío."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            tienda = Tienda.objects.get(pk=tienda_id)
        except Tienda.DoesNotExist:
            return Response({"error": "Tienda no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        
        line_items_for_stripe = []
        try:
            subtotal = Decimal('0.00')
            for item_data in items_data:
                producto = Producto.objects.get(
                    pk=item_data.get('producto_id'), 
                    tienda=tienda, 
                    estado=True
                )
                cantidad = int(item_data.get('cantidad'))
                
                if producto.stock < cantidad:
                    raise serializers.ValidationError(f"Stock insuficiente para {producto.nombre}")
                
                subtotal += (producto.precio * cantidad)

                line_items_for_stripe.append({
                    'price_data': {
                        'currency': 'bob',
                        'product_data': {
                            'name': producto.nombre,
                        },
                        'unit_amount': int(producto.precio * 100),
                    },
                    'quantity': cantidad,
                })

            
            costo_envio = calcular_costo_envio(subtotal)
            total_final = subtotal + costo_envio

        except Producto.DoesNotExist as e:
            return Response({"error": f"Producto no encontrado: {str(e)}"}, status=status.HTTP_404_NOT_FOUND)
        except serializers.ValidationError as e:
            return Response({"error": e.detail[0]}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Error al calcular el total: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
        try:
            metadata = {
                'user_id': request.user.id_usuario,
                'tienda_id': tienda.id,
                'direccion_entrega': direccion_entrega,
                'items_data': json.dumps(items_data)
            }

            if costo_envio > 0:
                line_items_for_stripe.append({
                    'price_data': {
                        'currency': 'bob',
                        'product_data': {
                            'name': 'Costo de Envío',
                        },
                        'unit_amount': int(costo_envio * 100),
                    },
                    'quantity': 1,
                })


            sesion_checkout = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items_for_stripe,
                mode='payment',
                metadata=metadata,
                customer_email=request.user.email,
                
                success_url=f"{settings.FRONTEND_URL}/tienda/{tienda.slug}/pago-exitoso?session_id={{CHECKOUT_SESSION_ID}}",
                
                cancel_url=f"{settings.FRONTEND_URL}/tienda/{tienda.slug}/pagar",
            )
            
            return Response({'url': sesion_checkout.url}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"Error al crear sesión de Stripe: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @action(detail=False, methods=['post'], url_path='verificar-sesion', 
            permission_classes=[permissions.IsAuthenticated]) # <-- CORREGIDO (con corchetes)
    def verificar_sesion_checkout(self, request):
        """
        Verifica una sesión de pago de Stripe después de la redirección
        y crea todos los objetos de la venta (Venta, Pago, Envio, etc.)
        """
        session_id = request.data.get('session_id')
        
        if not session_id:
            return Response({"error": "No se proporcionó session_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.status != 'complete':
                 return Response({"error": "La sesión de pago no está completada."}, status=status.HTTP_400_BAD_REQUEST)
            
            metadata = session.get('metadata', {})
            user_id = metadata.get('user_id')
            tienda_id = metadata.get('tienda_id')
            direccion_entrega = metadata.get('direccion_entrega')
            items_data_str = metadata.get('items_data')
            
            stripe_payment_id = session.get('payment_intent')
            total_pagado_centavos = session.get('amount_total')
            total_pagado = Decimal(total_pagado_centavos) / Decimal(100)

            if not all([user_id, tienda_id, direccion_entrega, items_data_str, stripe_payment_id]):
                print("Verificación de sesión recibió metadata incompleta.")
                return Response({"error": "Metadata incompleta en la sesión."}, status=500)
            
            try:
                items_data = json.loads(items_data_str)
            except json.JSONDecodeError:
                print("Error al decodificar items_data del JSON.")
                return Response(status=400)

            try:
                with transaction.atomic():
                    cliente = Cliente.objects.get(user_id=user_id) 
                    tienda = Tienda.objects.get(pk=tienda_id)
                    
                    asociacion, fue_creado = TiendaCliente.objects.get_or_create(
                        tienda=tienda,
                        cliente_id=user_id
                    )
                    
                    if fue_creado:
                        print(f"Nueva asociación creada: Cliente {user_id} a Tienda {tienda.nombre}")
                    else:
                        print(f"Asociación ya existía: Cliente {user_id} en Tienda {tienda.nombre}")

                    subtotal_seguro = Decimal('0.00')
                    productos_para_actualizar_stock = []
                    
                    detalles_carrito_a_crear = []
                    detalles_venta_a_crear = []

                    nuevo_carrito = Carrito.objects.create(
                        cliente=cliente,
                        tienda=tienda,
                        total=total_pagado
                    )

                    for item in items_data:
                        producto = Producto.objects.select_for_update().get(pk=item.get('producto_id'))
                        cantidad = int(item.get('cantidad'))
                        
                        if producto.stock < cantidad:
                            raise Exception(f"Stock insuficiente para {producto.nombre} durante la verificación.")
                        
                        precio_historico = producto.precio
                        subtotal_seguro += (precio_historico * cantidad)
                        
                        detalles_carrito_a_crear.append(
                            Detalle_Carrito(
                                carrito=nuevo_carrito,
                                producto=producto,
                                cantidad=cantidad,
                                precio_unitario=precio_historico
                            )
                        )
                        
                        producto.stock -= cantidad
                        productos_para_actualizar_stock.append(producto)

                    costo_envio_seguro = calcular_costo_envio(subtotal_seguro)
                    total_final_seguro = subtotal_seguro + costo_envio_seguro
                    
                    if total_final_seguro.quantize(Decimal('0.01')) != total_pagado.quantize(Decimal('0.01')):
                        raise Exception(f"Discrepancia de Total! Stripe cobró {total_pagado} pero el cálculo fue {total_final_seguro}")

                    nueva_venta = Venta.objects.create(
                        total=total_pagado,
                        estado='PROCESADA',
                        tienda=tienda,
                        cliente=cliente,
                        carrito=nuevo_carrito
                    )

                    for item in detalles_carrito_a_crear:
                        detalles_venta_a_crear.append(
                            Detalle_Venta(
                                venta=nueva_venta,
                                producto=item.producto,
                                cantidad=item.cantidad,
                                precio_historico=item.precio_unitario
                            )
                        )
                    
                    Pago.objects.create(
                        venta=nueva_venta,
                        tienda=tienda,
                        stripe_payment_intent_id=stripe_payment_id,
                        monto_total=total_pagado,
                        estado='COMPLETADO'
                    )
                    
                    Envio.objects.create(
                        venta=nueva_venta,
                        tienda=tienda,
                        direccion_entrega=direccion_entrega,
                        estado='EN_PREPARACION'
                    )

                    Detalle_Carrito.objects.bulk_create(detalles_carrito_a_crear)
                    Detalle_Venta.objects.bulk_create(detalles_venta_a_crear)
                    Producto.objects.bulk_update(productos_para_actualizar_stock, ['stock'])
                    
                    puntos_ganados = total_pagado * Decimal('0.0005')
                    cliente.puntos_acumulados += puntos_ganados
                    cliente.save(update_fields=['puntos_acumulados'])

                    log_action(
                        request=request,
                        accion="Compra procesada (Pago verificado)",
                        objeto=f"Venta #{nueva_venta.id} por Bs. {total_pagado} en {tienda.nombre}",
                        usuario=cliente.user # cliente.user es el User
                    )

            except Exception as e:
                print(f"Error al procesar la transacción de la sesión: {str(e)}")
                return Response({"error": f"Error al procesar el pedido: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({"success": True, "message": "Pedido creado exitosamente."}, status=status.HTTP_200_OK)

        except stripe.error.StripeError as e:
            return Response({"error": f"Error de Stripe: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": f"Error general: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class VentaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de SOLO LECTURA para que los clientes puedan ver
    su historial de ventas (pedidos).
    """
    serializer_class = VentaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    
    def get_queryset(self):
        """
        ¡Lógica de seguridad clave!
        
        Filtra el queryset para devolver SOLO las ventas
        del cliente actualmente autenticado.
        """
        user = self.request.user
        
        # Si el usuario no está logueado o no tiene un perfil de cliente
        if not user.is_authenticated or not hasattr(user, 'cliente_profile'):
            return Venta.objects.none()
        
        return Venta.objects.filter(
            cliente=user.cliente_profile
        ).select_related(
            'tienda', 
            'cliente__user__profile', 
            'envio'
        ).prefetch_related(
            'items__producto', 
            'pagos'
        ).order_by('-fecha_venta')
    
class VentaAdminViewSet(TenantAwareViewSet):
    """
    ¡NUEVO ViewSet!
    Permite a un Admin/Vendedor de una tienda gestionar
    TODAS las ventas de SU tienda.
    """
    serializer_class = VentaSerializer
    pagination_class = CustomPageNumberPagination
    
    # 1. Traemos todas las ventas con sus datos anidados
    queryset = Venta.objects.all().select_related(
        'tienda', 
        'cliente__user__profile', 
        'envio',
        'vendedor__user'
    ).prefetch_related(
        'items__producto', 
        'pagos'
    )
    
    # 2. Habilitamos filtros y búsqueda
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    search_fields = [
        'id', 
        'cliente__user__email', 
        'cliente__user__profile__nombre',
        'cliente__user__profile__apellido',
        'cliente__nit',
        'cliente__razon_social'
    ]
    
    filterset_fields = {
        'estado': ['exact', 'in'],
        'cliente__user_id': ['exact'],
        'vendedor__user_id': ['exact', 'isnull'],
        'fecha_venta': ['date__gte', 'date__lte'], # Filtrar por rango de fechas
    }
    
    ordering_fields = ['fecha_venta', 'total', 'estado']

    # 3. get_queryset() ya está manejado por TenantAwareViewSet,
    #    así que filtrará por 'tienda' automáticamente. ¡Perfecto!
    
    # 4. Habilitamos la edición (para tu futuro 'edit.jsx')
    #    (ReadOnlyModelViewSet no permite 'partial_update')
    def get_serializer_class(self):
        # (Podríamos usar un serializer más simple para 'update' en el futuro,
        # pero por ahora VentaSerializer sirve para 'list' y 'retrieve')
        return VentaSerializer

    def partial_update(self, request, *args, **kwargs):
        """
        Permite actualizar la Venta y sus estados anidados (Pago y Envio).
        El frontend debe enviar:
        {
            "estado": "NUEVO_ESTADO_VENTA" (Opcional)
            "pago_estado": "NUEVO_ESTADO_PAGO" (Opcional)
            "envio_estado": "NUEVO_ESTADO_ENVIO" (Opcional)
        }
        """
        instance = self.get_object()
        
        # 1. Obtener los nuevos estados del request
        nuevo_estado_venta = request.data.get('estado')
        nuevo_estado_pago = request.data.get('pago_estado')
        nuevo_estado_envio = request.data.get('envio_estado')

        # 2. Actualizar Estado de la Venta (si se envió)
        if nuevo_estado_venta:
            if nuevo_estado_venta not in [s[0] for s in Venta.ESTADOS_VENTA]:
                 return Response({"error": f"Estado '{nuevo_estado_venta}' no es válido para Venta."}, status=status.HTTP_400_BAD_REQUEST)
            instance.estado = nuevo_estado_venta
            instance.save(update_fields=['estado'])
            log_action(request, f"Actualizó estado de Venta #{instance.id} a {nuevo_estado_venta}", f"Venta ID: {instance.id}", request.user)

        # 3. Actualizar Estado del Pago (si se envió)
        if nuevo_estado_pago:
            pago = instance.pagos.first() # Asumimos que la venta tiene un pago principal
            if not pago:
                return Response({"error": "Esta venta no tiene un pago asociado para actualizar."}, status=status.HTTP_404_NOT_FOUND)
            
            if nuevo_estado_pago not in [s[0] for s in Pago.ESTADOS_PAGO]:
                 return Response({"error": f"Estado '{nuevo_estado_pago}' no es válido para Pago."}, status=status.HTTP_400_BAD_REQUEST)
            
            pago.estado = nuevo_estado_pago
            pago.save(update_fields=['estado'])
            log_action(request, f"Actualizó estado de Pago #{pago.id} a {nuevo_estado_pago}", f"Venta ID: {instance.id}", request.user)

        # 4. Actualizar Estado del Envío (si se envió)
        if nuevo_estado_envio:
            envio = instance.envio # La Venta tiene un OneToOneField con Envio
            if not envio:
                return Response({"error": "Esta venta no tiene un envío asociado para actualizar."}, status=status.HTTP_404_NOT_FOUND)

            if nuevo_estado_envio not in [s[0] for s in Envio.ESTADOS_ENVIO]:
                 return Response({"error": f"Estado '{nuevo_estado_envio}' no es válido para Envío."}, status=status.HTTP_400_BAD_REQUEST)

            envio.estado = nuevo_estado_envio
            envio.save(update_fields=['estado'])
            log_action(request, f"Actualizó estado de Envío #{envio.id} a {nuevo_estado_envio}", f"Venta ID: {instance.id}", request.user)


        # Devolvemos la instancia de Venta actualizada y serializada
        serializer = self.get_serializer(instance)
        return Response(serializer.data)