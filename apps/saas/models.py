from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.utils.text import slugify
from cloudinary_storage.storage import MediaCloudinaryStorage

# Modelo Planes de Suscripción SaaS
class PlanSuscripcion(models.Model):
    PLAN_SUSCRIPCION = [
        ('PRUEBA', 'Prueba'),
        ('BASICO-M', 'Básico-M'),
        ('PREMIUM-M', 'Premium-M'),
        ('BASICO-A', 'Básico-A'),
        ('PREMIUM-A', 'Premium-A'),  
    ]
    nombre = models.CharField(max_length=50, unique=True, choices=PLAN_SUSCRIPCION, verbose_name="Nombre del Plan")
    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio Mensual")
    limite_usuarios = models.IntegerField(default=5, verbose_name="Límite de Usuarios (Staff)")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    dias_prueba = models.IntegerField(default=0, help_text="Duración en días para planes de prueba. 0 para planes de pago.")
    stripe_price_id = models.CharField(max_length=100, blank=True, null=True, help_text="ID del objeto Price de Stripe")

    def __str__(self):
        if self.nombre == 'PRUEBA':
            return f"Plan de Prueba ({self.dias_prueba} días)"
        return f"{self.get_nombre_display()} (${self.precio_mensual}/mes)"

    class Meta:
        verbose_name = "Plan de Suscripción"
        verbose_name_plural = "Planes de Suscripción"

# Modelo TIENDA (Tenant)
class Tienda(models.Model):
    ESTADOS_SUSCRIPCION = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
        ('CANCELADO', 'Cancelado'),
        ('PRUEBA', 'Prueba'),
    ]
    plan = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.PROTECT,
        related_name='tiendas',
        verbose_name="Plan Contratado"
    )
    nombre = models.CharField(max_length=100, verbose_name="Nombre de la Tienda/Empresa")
    fecha_inicio_servicio = models.DateField(auto_now_add=True, verbose_name="Fecha de Inicio")
    fecha_proximo_cobro = models.DateField(verbose_name="Próximo Cobro", null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_SUSCRIPCION, default='ACTIVO', verbose_name="Estado de Suscripción")
    
    admin_contacto = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tienda_administrada',
        verbose_name="Admin de Contacto"
    )
    
    clientes = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='TiendaCliente', # Le indicamos que use nuestro modelo puente
        related_name='tiendas_como_cliente'
    )

    # --- CAMPOS NUEVOS AÑADIDOS PARA EL PERFIL PÚBLICO ---
    # Para la URL (ej: /store/mi-tienda-cool)
    slug = models.SlugField(
        max_length=100, 
        unique=True, 
        db_index=True, 
        null=True, 
        blank=True
    )
    
    # Para los filtros de búsqueda (ej: Ropa, Electrónica)
    rubro = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        default="General"
    )
    
    # Para la StoreCard (el eslogan)
    descripcion_corta = models.CharField(
        max_length=150, 
        null=True, 
        blank=True
    )
    
    # Para la identidad visual (Logo y Banner)
    logo = models.ImageField(
        upload_to='logos_tiendas/',
        storage=MediaCloudinaryStorage(),
        null=True, blank=True
    )
    banner = models.ImageField(
        upload_to='banners_tiendas/',
        storage=MediaCloudinaryStorage(),
        null=True, blank=True
    )

    def save(self, *args, **kwargs):
        # Si no hay slug, créalo desde el nombre
        if not self.slug:
            self.slug = slugify(self.nombre)
            # Nos aseguramos de que sea único
            original_slug = self.slug
            counter = 1
            while Tienda.objects.filter(slug=self.slug).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1

        if not self.pk and self.plan: # si es un objeto nuevo
            if self.plan.dias_prueba > 0:
                self.fecha_proximo_cobro = timezone.now().date() + relativedelta(days=self.plan.dias_prueba)
                self.estado = 'PRUEBA'
            else:
                self.fecha_proximo_cobro = timezone.now().date() + relativedelta(months=1)
                self.estado = 'ACTIVO'
        super().save(*args, **kwargs)


    def __str__(self):
        return f"Tienda: {self.nombre} - Plan: {self.plan.get_nombre_display()}"

    class Meta:
        verbose_name = "Tienda (Tenant)"
        verbose_name_plural = "Tiendas (Tenants)"
        ordering = ['nombre']

# Modelo Puente para la relación Many-to-Many entre Tienda y Cliente
class TiendaCliente(models.Model):
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE)
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    fecha_asociacion = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('tienda', 'cliente') # Evita que un cliente se asocie dos veces a la misma tienda
        verbose_name = "Cliente de Tienda"
        verbose_name_plural = "Clientes de Tiendas"
    
    def __str__(self):
        return f"Cliente {self.cliente.email} en Tienda {self.tienda.nombre}"

# Modelo Pagos de Suscripción
class PagoSuscripcion(models.Model):
    ESTADOS_PAGO = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('FALLIDO', 'Fallido'),
    ]

    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE,
        related_name='pagos_suscripcion',
        verbose_name="Tienda"
    )
    plan_pagado = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.PROTECT,
        related_name='pagos',
        verbose_name="Plan Pagado"
    )
    stripe_payment_intent_id = models.CharField(max_length=100, unique=True, blank=True, null=True, verbose_name="ID de Payment Intent de Stripe")
    monto_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto Total")
    fecha_emision = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Emisión")
    fecha_pago = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de Pago")
    estado = models.CharField(max_length=20, choices=ESTADOS_PAGO, default='PAGADO', verbose_name="Estado del Pago")
    
    def __str__(self):
        return f"Pago #{self.id} de {self.tienda.nombre} por ${self.monto_total}"

    class Meta:
        verbose_name = "Pago de Suscripción"
        verbose_name_plural = "Pagos de Suscripción"
        ordering = ['-fecha_emision']

