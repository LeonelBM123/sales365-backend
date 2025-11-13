from django.conf import settings
from django.db import models
from cloudinary_storage.storage import MediaCloudinaryStorage
from apps.saas.models import Tienda
from apps.users.models import Cliente

# --- Modelos de Producto y Catálogo ---
class Marca(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    estado = models.BooleanField(default=True)
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return self.nombre

class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    estado = models.BooleanField(default=True)
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return self.nombre

# --- Modelo de Auditoria de Precios ---
class LogPrecioProducto(models.Model):
    producto = models.ForeignKey(
        'Producto',
        on_delete=models.CASCADE,
        related_name="historial_precios"
    )
    precio_anterior = models.DecimalField(max_digits=10, decimal_places=2)
    precio_nuevo = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_cambio = models.DateTimeField(auto_now_add=True)
    
    usuario_que_modifico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        try:
            return f"Cambio de {self.producto.nombre} a {self.precio_nuevo} el {self.fecha_cambio.date()}"
        except Exception:
            return f"Cambio de precio a {self.precio_nuevo} el {self.fecha_cambio.date()}"

    class Meta:
        ordering = ['-fecha_cambio']

class Producto(models.Model):
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    codigo_referencia = models.CharField(max_length=50, blank=True, null=True, unique=True)
    estado = models.BooleanField(default=True)
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE
    )
    marca = models.ForeignKey(
        Marca,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    categorias = models.ManyToManyField(
        Categoria,
        related_name="productos",
        blank=True
    )

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        """
        Sobrescribe el método save para crear un log de precio
        cuando el precio cambie.
        """
        usuario = kwargs.pop('usuario', None)

        if not self._state.adding: 
            try:
                original = Producto.objects.get(pk=self.pk)
                
                if original.precio != self.precio:
                    LogPrecioProducto.objects.create(
                        producto=self,
                        precio_anterior=original.precio,
                        precio_nuevo=self.precio,
                        usuario_que_modifico=usuario 
                    )
            except Producto.DoesNotExist:
                pass 
        
        super().save(*args, **kwargs)

class Foto(models.Model):
    foto = models.ImageField(
        upload_to='fotos_productos/',
        storage=MediaCloudinaryStorage(),
        null=True,
        blank=True
    )
    principal = models.BooleanField(default=False)
    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="fotos"
    )

# --- Modelos de Carrito ---
class Carrito(models.Model):
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="carritos"
    )
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    def __str__(self):
        try:
            nombre = self.cliente.user.profile.nombre
            return f"Carrito de {nombre} ({self.cliente.user.email}) - {self.fecha_creacion.date()}"
        except Exception:
            return f"Carrito de {self.cliente.user.email} - {self.fecha_creacion.date()}"


class Detalle_Carrito(models.Model):
    cantidad = models.PositiveIntegerField(default=1)
    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE
    )
    carrito = models.ForeignKey(
        Carrito,
        on_delete=models.CASCADE,
        related_name="items"
    )
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    class Meta:
        unique_together = ('carrito', 'producto')