from rest_framework import serializers
from .models import Venta, Detalle_Venta, Pago, Envio

# Importamos modelos de otras apps para anidar la información
from apps.users.models import Cliente
from apps.comercial.models import Producto

# --- Serializers de Soporte ---
class ClienteSimpleSerializer(serializers.ModelSerializer):
    """
    Serializer simple para mostrar la información básica del cliente
    dentro de un pedido.
    """
    nombre_completo = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email')
    
    class Meta:
        model = Cliente
        fields = ('user_id', 'email', 'nombre_completo', 'nit', 'razon_social')
        
    def get_nombre_completo(self, obj):
        try:
            # Asumimos que el User tiene una relación 'profile'
            return f"{obj.user.profile.nombre} {obj.user.profile.apellido}"
        except Exception:
            # Si no tiene profile, devolvemos el email como fallback
            return obj.user.email

class ProductoSimpleVentaSerializer(serializers.ModelSerializer):
    """
    Serializer súper ligero para mostrar el producto dentro
    del detalle de venta.
    """
    class Meta:
        model = Producto
        fields = ('id', 'nombre', 'codigo_referencia')


# --- Serializers Principales de la App 'ventas' ---
class PagoSerializer(serializers.ModelSerializer):
    """
    Muestra la información de un pago.
    """
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    
    class Meta:
        model = Pago
        fields = (
            'id', 
            'stripe_payment_intent_id', 
            'monto_total', 
            'estado', 
            'estado_display', 
            'fecha_creacion'
        )

class EnvioSerializer(serializers.ModelSerializer):
    """
    Muestra la información de un envío.
    """
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    
    class Meta:
        model = Envio
        fields = ('id', 'direccion_entrega', 'estado', 'estado_display')

class DetalleVentaSerializer(serializers.ModelSerializer):
    """
    Muestra un item (producto) dentro de una venta.
    """
    producto = ProductoSimpleVentaSerializer(read_only=True)
    subtotal = serializers.SerializerMethodField()
    
    class Meta:
        model = Detalle_Venta
        fields = ('id', 'producto', 'cantidad', 'precio_historico', 'subtotal')
        
    def get_subtotal(self, obj):
        """ Calcula el subtotal basado en el precio guardado """
        return (obj.cantidad * obj.precio_historico)

class VentaSerializer(serializers.ModelSerializer):
    """
    Serializer principal para una Venta.
    Anida toda la información: items, pago, envío y cliente.
    Ideal para una página de "Detalle de Pedido".
    """
    items = DetalleVentaSerializer(many=True, read_only=True)
    pagos = PagoSerializer(many=True, read_only=True)
    envio = EnvioSerializer(read_only=True)
    cliente = ClienteSimpleSerializer(read_only=True)
    tienda = serializers.StringRelatedField(read_only=True)
    vendedor = serializers.StringRelatedField(read_only=True) # Muestra el email del vendedor
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    
    class Meta:
        model = Venta
        fields = (
            'id', 
            'fecha_venta', 
            'total', 
            'estado', 
            'estado_display', 
            'tienda', 
            'cliente', 
            'vendedor', 
            'carrito',
            'items', 
            'pagos', 
            'envio'
        )