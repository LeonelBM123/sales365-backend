from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.saas.models import Tienda
from apps.users.models import Cliente, Vendedor

# --- Modelo Venta ---
class Venta(models.Model):
    ESTADOS_VENTA = [
        ('PROCESADA', 'Procesada'),
        ('ENVIADA', 'Enviada'),
        ('ENTREGADA', 'Entregada'),
        ('CANCELADA', 'Cancelada'),
    ]

    fecha_venta = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Venta")
    total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Total Venta")
    estado = models.CharField(max_length=50, choices=ESTADOS_VENTA, default="PROCESADA")
    
    # --- Relaciones Clave ---
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.PROTECT, 
        related_name="ventas"
    )
    cliente = models.ForeignKey(
        Cliente, 
        on_delete=models.PROTECT, 
        related_name="compras"
    )
    
    # --- Vendedor (opcional) ---
    vendedor = models.ForeignKey(
        Vendedor,
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="ventas_asignadas"
    )
    
    # --- Lógica de Carrito ---
    carrito = models.OneToOneField(
        'comercial.Carrito', 
        on_delete=models.PROTECT, 
        related_name="venta_carrito"
    )

    def __str__(self):
        return f"Venta {self.id} - {self.cliente.user.email}"

    class Meta:
        verbose_name = "Venta"
        verbose_name_plural = "Ventas"
        ordering = ['-fecha_venta']


class Detalle_Venta(models.Model):
    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="items" 
    )
    producto = models.ForeignKey(
        'comercial.Producto', 
        on_delete=models.PROTECT, 
        related_name="items_vendidos"
    )
    cantidad = models.PositiveIntegerField()
    precio_historico = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio Histórico") 

    def __str__(self):
        try:
            return f"{self.cantidad} x {self.producto.nombre} @ {self.precio_historico}"
        except Exception:
            return f"{self.cantidad} x [Producto no disponible] @ {self.precio_historico}"
    
    class Meta:
        verbose_name = "Detalle de Venta"
        verbose_name_plural = "Detalles de Venta"


# --- Modelo Pago ---
class Pago(models.Model):
    ESTADOS_PAGO = [
        ('PENDIENTE', 'Pendiente'),
        ('COMPLETADO', 'Completado'),
        ('FALLIDO', 'Fallido'),
        ('REEMBOLSADO', 'Reembolsado'),
    ]
    
    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="pagos"
    )
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.PROTECT,
        related_name="pagos_recibidos"
    )
    
    stripe_payment_intent_id = models.CharField(max_length=100, unique=True, blank=True, null=True, verbose_name="ID Payment Intent (Stripe)")
    monto_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto Total")
    estado = models.CharField(max_length=20, choices=ESTADOS_PAGO, default='PENDIENTE')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Pago {self.id} para Venta {self.venta.id} - {self.get_estado_display()}"
    
    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"


# --- Modelo Envío ---
class Envio(models.Model):
    ESTADOS_ENVIO = [
        ('EN_PREPARACION', 'En preparación'),
        ('EN_CAMINO', 'En camino'),
        ('ENTREGADO', 'Entregado'),
        ('INCIDENCIA', 'Incidencia'),
    ]

    venta = models.OneToOneField(
        Venta,
        on_delete=models.CASCADE,
        related_name="envio" 
    )
    
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.PROTECT,
        related_name="envios_realizados"
    )
    
    direccion_entrega = models.TextField(verbose_name="Dirección de Entrega")
    estado = models.CharField(max_length=20, choices=ESTADOS_ENVIO, default='EN_PREPARACION')

    def __str__(self):
        return f"Envío para Venta {self.venta.id} - {self.get_estado_display()}"

    class Meta:
        verbose_name = "Envío"
        verbose_name_plural = "Envíos"


# --- LÓGICA DE SIGNALS ---
# Esta función se ejecutará cada vez que un modelo Venta sea guardado.
@receiver(post_save, sender=Venta)
def actualizar_conteo_ventas_vendedor(sender, instance, created, **kwargs):
    """
    Escucha la creación de una Venta. Si se crea una nueva venta
    y tiene un vendedor asignado, incrementa el contador 
    de 'ventas_realizadas' de ese vendedor.
    
    También maneja el caso de que se CANCELE una venta, restando la venta.
    """
    vendedor = instance.vendedor
    if not vendedor:
        return # Si no hay vendedor, no hace nada

    if created:
        # Si la venta es nueva, suma 1
        vendedor.ventas_realizadas += 1
        vendedor.save(update_fields=['ventas_realizadas'])
    
    # Lógica adicional: Si la venta se marca como CANCELADA
    if instance.estado == 'CANCELADA':
        # Para evitar que se reste varias veces, necesitamos el estado original
        try:
            original = Venta.objects.get(pk=instance.pk)
            if original.estado != 'CANCELADA':
                # Si acaba de ser cancelada, resta 1
                if vendedor.ventas_realizadas > 0:
                    vendedor.ventas_realizadas -= 1
                    vendedor.save(update_fields=['ventas_realizadas'])
        except Venta.DoesNotExist:
            pass

