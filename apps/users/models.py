from django.conf import settings
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# --- MODELO DE ROL ---
class Rol(models.Model):
    OPCIONES_ESTADO = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
    ]
    OPCIONES_NOMBRE = [
        ('superAdmin', 'Super Administrador'),
        ('admin', 'Administrador'),
        ('cliente', 'Cliente'),
        ('vendedor', 'Vendedor'),
    ]
    nombre = models.CharField(max_length=50, choices=OPCIONES_NOMBRE, unique=True)
    estado = models.CharField(max_length=10, choices=OPCIONES_ESTADO, default='ACTIVO')
    descripcion = models.TextField()

    def __str__(self):
        return self.get_nombre_display()
    
    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

# --- GESTOR DE USUARIOS PERSONALIZADO ---
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es un campo obligatorio.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if not extra_fields.get('is_staff'): raise ValueError('Superuser debe tener is_staff=True.')
        if not extra_fields.get('is_superuser'): raise ValueError('Superuser debe tener is_superuser=True.')
        
        if 'rol' not in extra_fields:
            rol, _ = Rol.objects.get_or_create(nombre='superAdmin', defaults={'descripcion': 'Acceso total al sistema.'})
            extra_fields['rol'] = rol
        return self.create_user(email, password, **extra_fields)

# --- MODELO DE USUARIO PRINCIPAL ---
class User(AbstractBaseUser, PermissionsMixin):
    id_usuario = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True, verbose_name="Activo")
    is_staff = models.BooleanField(default=False, verbose_name="Es Staff (acceso al admin)")
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, null=True, blank=True)

    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    # --- MÉTODOS PERSONALIZADOS  ---
    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_staff

    def puede_acceder_sistema(self):
        """
        Verifica si el usuario puede acceder al sistema SaaS (Dashboard).
        ¡Esta función NO debe permitir el acceso a 'cliente'!
        """
        # 1. Comprobaciones básicas
        if not self.is_active:
            return False
        if not self.rol:
            return False

        # 2. Lista de roles que SÍ pueden acceder al dashboard
        roles_permitidos_saas = ['admin', 'superAdmin', 'vendedor']

        # 3. ¡COMPROBACIÓN CRÍTICA!
        #    Rechaza si el rol NO está en la lista permitida (ej. 'cliente')
        if self.rol.nombre not in roles_permitidos_saas:
            return False 

        # 4. superAdmin siempre entra
        if self.rol.nombre == 'superAdmin':
            return True

        # 5. Para 'admin' y 'vendedor', comprueba el estado
        return self.rol.estado == 'ACTIVO'

    def __str__(self):
        rol_nombre = self.rol.get_nombre_display() if self.rol else "Sin Rol"
        return f"{self.email} ({rol_nombre})"
    
    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
    
# --- PERFILES DE USUARIO ---
class UserProfile(models.Model):
    OPCIONES_GENERO = [
        ('MASCULINO', 'Masculino'),
        ('FEMENINO', 'Femenino'),
        ('OTRO', 'Otro'),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile', primary_key=True)
    ci = models.CharField(max_length=20, unique=True, blank=True, null=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    direccion = models.TextField(blank=True, null=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    foto_perfil = models.ImageField(
        upload_to='fotos_perfil/',
        storage=MediaCloudinaryStorage(),
        null=True,
        blank=True
    )
    genero = models.CharField(max_length=20, choices=OPCIONES_GENERO, null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

class Cliente(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cliente_profile', primary_key=True)
    nivel_fidelidad = models.CharField(max_length=50, default='Bronce')
    puntos_acumulados = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Puntos_Acumulados", default=0.00) 
    nit = models.CharField(
        max_length=20, 
        unique=True, 
        null=True, 
        blank=True, 
        db_index=True
    )
    razon_social = models.CharField(
        max_length=255, 
        null=True, 
        blank=True
    )

    def __str__(self):
        return f"Cliente: {self.user.email}"
    
class Vendedor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vendedor_profile', primary_key=True)
    fecha_contratacion = models.DateField(null=True, blank=True)
    ventas_realizadas = models.IntegerField(default=0)
    tasa_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tienda = models.ForeignKey(
        'saas.Tienda', 
        on_delete=models.CASCADE,
        related_name='vendedores'
    )

    def __str__(self):
        return f"Vendedor: {self.user.email} en {self.tienda.nombre}"
    
class Administrador(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_profile', primary_key=True)
    departamento = models.CharField(max_length=100, null=True, blank=True)
    fecha_contratacion = models.DateField(null=True, blank=True)
    tienda = models.ForeignKey(
        'saas.Tienda', 
        on_delete=models.CASCADE,
        related_name='administradores'
    )

    def __str__(self):
        return f"Administrador: {self.user.email} en {self.tienda.nombre}"