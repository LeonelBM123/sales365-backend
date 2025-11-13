from rest_framework import serializers
from django.db import transaction
from apps.saas.models import Tienda
from .models import User, Rol, UserProfile, Cliente, Vendedor, Administrador

# --- Serializers de base (sin cambios) ---
class RolSerializer(serializers.ModelSerializer):
    class Meta: 
        model = Rol; 
        fields = ['id', 'nombre', 'descripcion', 'estado']

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta: 
        model = UserProfile; 
        exclude = ['user']

# --- Serializers de Perfil para ESCRITURA (usados en la creación anidada) ---
class VendedorProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Vendedor; fields = ['fecha_contratacion', 'tasa_comision']

class AdministradorProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Administrador; fields = ['departamento', 'fecha_contratacion']

class ClienteProfileWriteSerializer(serializers.ModelSerializer):
    class Meta: model = Cliente; fields = ['nivel_fidelidad', 'puntos_acumulados', 'nit', 'razon_social']

# --- Serializers de Detalle (para vistas de lista/detalle) ---
class TiendaBasicSerializer(serializers.ModelSerializer):
    class Meta: model = Tienda; fields = ['id', 'nombre']

class UserBasicSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    class Meta: model = User; fields = ['id_usuario', 'email', 'profile']

class ClienteDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    class Meta: model = Cliente; fields = '__all__'

class VendedorDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    tienda = TiendaBasicSerializer(read_only=True)
    class Meta: model = Vendedor; fields = '__all__'

class AdministradorDetailSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    tienda = TiendaBasicSerializer(read_only=True)
    class Meta: model = Administrador; fields = '__all__'

# --- Serializer Principal de User  ---
class UserSerializer(serializers.ModelSerializer):
    rol_id = serializers.PrimaryKeyRelatedField(queryset=Rol.objects.all(), source='rol', write_only=True)
    rol = RolSerializer(read_only=True)
    profile = UserProfileSerializer()
    tienda_id = serializers.PrimaryKeyRelatedField(queryset=Tienda.objects.all(), required=False, allow_null=True, write_only=True, source='tienda')

    # Perfiles de solo escritura
    vendedor_profile = VendedorProfileWriteSerializer(required=False, allow_null=True)
    admin_profile = AdministradorProfileWriteSerializer(required=False, allow_null=True)
    cliente_profile = ClienteProfileWriteSerializer(required=False, allow_null=True)

    cliente_profile_data = ClienteDetailSerializer(source='cliente_profile', read_only=True)

    class Meta:
        model = User
        fields = [
            'id_usuario', 'email', 'password', 'rol', 'rol_id', 'tienda_id', 'is_active', 
            'fecha_creacion', 'profile', 'vendedor_profile', 'admin_profile', 'cliente_profile',
            'cliente_profile_data'
        ]
        extra_kwargs = {'password': {'write_only': True}}

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Maneja la actualización del User y sus perfiles anidados (UserProfile, Vendedor, Admin).
        """
        # 1. Sacamos TODOS los diccionarios de perfiles anidados
        profile_data = validated_data.pop('profile', None)
        vendedor_data = validated_data.pop('vendedor_profile', None)
        admin_data = validated_data.pop('admin_profile', None)
        cliente_data = validated_data.pop('cliente_profile', None)

        # 2. Actualizamos los campos directos del User (email, is_active, rol_id)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save() # Guardamos la instancia del User

        # 3. Actualizamos el UserProfile (genérico)
        if profile_data and hasattr(instance, 'profile'):
            profile = instance.profile
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save() 
        
        # 4. Actualizamos el VendedorProfile (específico)
        if vendedor_data and hasattr(instance, 'vendedor_profile'):
            vendedor_profile = instance.vendedor_profile
            for attr, value in vendedor_data.items():
                setattr(vendedor_profile, attr, value)
            vendedor_profile.save()

        # 5. Actualizamos el AdministradorProfile (específico)
        if admin_data and hasattr(instance, 'admin_profile'):
            admin_profile = instance.admin_profile
            for attr, value in admin_data.items():
                setattr(admin_profile, attr, value)
            admin_profile.save()

        # 6. Actualizamos el ClienteProfile
        if cliente_data and hasattr(instance, 'cliente_profile'):
            cliente_profile = instance.cliente_profile
            for attr, value in cliente_data.items():
                setattr(cliente_profile, attr, value)
            cliente_profile.save()

        return instance

    @transaction.atomic
    def create(self, validated_data):
        profile_data = validated_data.pop('profile')
        rol = validated_data.get('rol')
        tienda = validated_data.pop('tienda', None) or self.context.get('tienda_forzada')
        
        # Saca los perfiles específicos (incluso si están vacíos)
        vendedor_data = validated_data.pop('vendedor_profile', None) or {}
        admin_data = validated_data.pop('admin_profile', None) or {}
        cliente_data = validated_data.pop('cliente_profile', None) or {}

        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user, **profile_data)

        if rol:
            if rol.nombre == 'vendedor':
                if not tienda: raise serializers.ValidationError("Un Vendedor debe estar asociado a una tienda.")
                Vendedor.objects.create(user=user, tienda=tienda, **vendedor_data)
            elif rol.nombre == 'admin':
                if not tienda: raise serializers.ValidationError("Un Administrador debe estar asociado a una tienda.")
                Administrador.objects.create(user=user, tienda=tienda, **admin_data)
            elif rol.nombre == 'cliente':
                Cliente.objects.create(user=user, **cliente_data)
                if tienda: tienda.clientes.add(user)
        return user

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        rol_nombre = instance.rol.nombre if instance.rol else None
        
        tienda_data = None
        if rol_nombre == 'admin' and hasattr(instance, 'admin_profile'):
            tienda = instance.admin_profile.tienda
            tienda_data = {'id': tienda.id, 'nombre': tienda.nombre}
        elif rol_nombre == 'vendedor' and hasattr(instance, 'vendedor_profile'):
            tienda = instance.vendedor_profile.tienda
            tienda_data = {'id': tienda.id, 'nombre': tienda.nombre}
        
        representation['tienda'] = tienda_data
        # Limpiamos los campos write_only de la respuesta
        representation.pop('vendedor_profile', None)
        representation.pop('admin_profile', None)
        representation.pop('cliente_profile', None)
        return representation



# --- SERIALIZERS PARA EDITAR PERFIL ---
# --- SERIALIZADOR 1: Solo los campos del perfil anidado ---
class ProfileDataSerializer(serializers.ModelSerializer):
    """
    Serializador anidado que SOLO contiene los campos que el usuario
    puede editar de su UserProfile.
    """
    class Meta:
        model = UserProfile
        fields = (
            'ci', 
            'nombre', 
            'apellido', 
            'direccion', 
            'fecha_nacimiento', 
            'telefono', 
            'genero'
        )

# --- SERIALIZADOR 2: Para actualizar el perfil (email + datos) ---
class UserProfileUpdateSerializer(serializers.ModelSerializer):
    profile = serializers.DictField(required=False)

    cliente_profile = serializers.DictField(required=False, write_only=True)

    class Meta:
        model = User
        fields = ['email', 'profile', 'cliente_profile']  # agrega otros campos de User si tienes

    def update(self, instance, validated_data):
        # Extrae datos del perfil si existen
        profile_data = validated_data.pop('profile', None)

        cliente_data = validated_data.pop('cliente_profile', None)

        # Actualiza campos del usuario
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Actualiza perfil existente (no crea uno nuevo)
        if profile_data:
            profile = instance.profile  # acceso al perfil actual
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        if cliente_data and hasattr(instance, 'cliente_profile'):
            cliente_profile = instance.cliente_profile
            # Iteramos solo sobre los campos que permitimos
            for attr, value in cliente_data.items():
                if attr in ['nit', 'razon_social']:
                    setattr(cliente_profile, attr, value)
            cliente_profile.save()

        return instance

# --- SERIALIZADOR 3: Para cambiar la contraseña del propio usuario ---
class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializador para el cambio de contraseña del propio usuario.
    Valida la contraseña antigua antes de permitir el cambio.
    """
    old_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    def validate_old_password(self, value):
        """
        Valida que la contraseña antigua (old_password) sea correcta.
        """
        # Obtenemos el usuario del contexto (que pasaremos desde la vista)
        user = self.context['request'].user
        
        if not user.check_password(value):
            raise serializers.ValidationError("Tu contraseña antigua no es correcta.")
        
        return value

    def validate_new_password(self, value):
        """
        (Opcional) Puedes agregar validaciones de fortaleza de contraseña aquí.
        Por ejemplo, que tenga al menos 8 caracteres.
        """
        if len(value) < 8:
            raise serializers.ValidationError("La nueva contraseña debe tener al menos 8 caracteres.")
        return value
    
# -- SERIALIZADOR 4: EDITAR FOTO DE PERFIL --
class UserPhotoSerializer(serializers.ModelSerializer):
    foto_perfil_url = serializers.SerializerMethodField()
    
    class Meta:
        model = UserProfile
        fields = ['foto_perfil', 'foto_perfil_url']
        read_only_fields = ['foto_perfil_url']
    
    def get_foto_perfil_url(self, obj):
        """Devuelve la URL completa de Cloudinary"""
        if obj.foto_perfil:
            return obj.foto_perfil.url  # Cloudinary proporciona .url automáticamente
        return None
    
    def to_representation(self, instance):
        """Transforma la respuesta para devolver solo la URL"""
        data = super().to_representation(instance)
        # Reemplaza el campo file por la URL en la respuesta
        data['foto_perfil'] = data.get('foto_perfil_url')
        return data
    
class CustomerRegisterSerializer(serializers.ModelSerializer):
    """
    Serializador simple para el registro PÚBLICO de clientes.
    Toma datos básicos y crea el User, UserProfile, y Cliente.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, min_length=8, style={'input_type': 'password'})
    nombre = serializers.CharField(required=True, write_only=True)
    apellido = serializers.CharField(required=True, write_only=True)
    telefono = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'nombre', 'apellido', 'telefono')

    def validate_email(self, value):
        """Valida que el email no esté ya en uso."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Este correo electrónico ya está en uso.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        # 1. Encontrar el Rol 'cliente'
        try:
            rol_cliente = Rol.objects.get(nombre='cliente')
        except Rol.DoesNotExist:
            # Esto es un error de configuración del servidor, no del usuario
            raise serializers.ValidationError("El rol 'cliente' no está configurado en el sistema.")

        # 2. Crear el User
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            rol=rol_cliente
        )

        # 3. Crear el UserProfile
        UserProfile.objects.create(
            user=user,
            nombre=validated_data['nombre'],
            apellido=validated_data['apellido'],
            telefono=validated_data.get('telefono', '')
        )

        # 4. Crear el perfil Cliente (vacío, listo para usarse)
        Cliente.objects.create(user=user)

        return user