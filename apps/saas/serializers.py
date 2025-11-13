from rest_framework import serializers
from .models import PlanSuscripcion, Tienda, PagoSuscripcion
from apps.users.models import User

class TiendaPublicSerializer(serializers.ModelSerializer):
    """
    Serializer ReadOnly para la lista pública de tiendas.
    Solo expone datos seguros y públicos.
    """
    logo_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = Tienda
        fields = [
            'id', 'nombre', 'slug', 'rubro', 
            'descripcion_corta', 'logo_url', 'banner_url'
        ]
    
    def get_logo_url(self, obj):
        if obj.logo and hasattr(obj.logo, 'url') and obj.logo.url:
            url = obj.logo.url
            # --- ¡MAGIA AQUÍ! ---
            # c_fill: Recorta para llenar el área.
            # ar_1:1: Proporción (Aspect Ratio) 1:1 (cuadrado).
            # g_auto: Punto focal automático (inteligente) para el recorte.
            transformation = "c_fill,ar_1:1,g_auto"
            
            # Inyectamos la transformación en la URL
            return url.replace("/image/upload/", f"/image/upload/{transformation}/")
        
        return None # O una URL a un logo por defecto

    def get_banner_url(self, obj):
        if obj.banner and hasattr(obj.banner, 'url') and obj.banner.url:
            url = obj.banner.url
            # --- ¡MAGIA AQUÍ! ---
            # c_fill: Recorta para llenar el área.
            # ar_16:9: Proporción (Aspect Ratio) 16:9 (video).
            # g_auto: Punto focal automático (inteligente) para el recorte.
            transformation = "c_fill,ar_16:9,g_auto"
            
            # Inyectamos la transformación en la URL
            return url.replace("/image/upload/", f"/image/upload/{transformation}/")
        
        return None # O una URL a un banner por defecto

# Serializer para el formulario de registro público
class RegistroSerializer(serializers.Serializer):
    """
    Serializer para validar los datos del formulario de registro público.
    No está ligado a un modelo, solo valida la entrada.
    """
    plan_id = serializers.IntegerField()
    tienda_nombre = serializers.CharField(max_length=100)
    
    # Campos del perfil público (opcionales al registrarse)
    slug = serializers.SlugField(max_length=100, required=False, allow_blank=True)
    rubro = serializers.CharField(max_length=100, required=False, allow_blank=True)
    descripcion_corta = serializers.CharField(max_length=150, required=False, allow_blank=True)
    
    # Campos del admin
    admin_nombre = serializers.CharField(max_length=100)
    admin_apellido = serializers.CharField(max_length=100)
    admin_ci = serializers.CharField(max_length=20)
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField(write_only=True, min_length=8)
    admin_telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)


# Serializer para mostrar información básica del admin de contacto
class AdminContactoSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id_usuario', 'email', 'nombre_completo']

    def get_nombre_completo(self, obj):
        return f"{obj.profile.nombre} {obj.profile.apellido}" if hasattr(obj, 'profile') else obj.email

# --- Serializers Principales ---
class PlanSuscripcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanSuscripcion
        fields = '__all__'

class TiendaSerializer(serializers.ModelSerializer):
    """Serializer para crear y actualizar una Tienda."""
    class Meta:
        model = Tienda
        fields = ['id', 'plan', 'nombre', 'fecha_proximo_cobro', 'estado', 'admin_contacto',
                  'slug', 'rubro', 'descripcion_corta', 'logo', 'banner']

class TiendaDetailSerializer(serializers.ModelSerializer):
    """Serializer para ver los detalles de una Tienda."""
    plan = PlanSuscripcionSerializer(read_only=True)
    admin_contacto = AdminContactoSerializer(read_only=True)
    
    # Obtenemos las URLs directamente
    logo_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = Tienda
        fields = [
            'id', 'plan', 'nombre', 'fecha_inicio_servicio', 
            'fecha_proximo_cobro', 'estado', 'admin_contacto',
            'slug', 'rubro', 'descripcion_corta', 'logo_url', 'banner_url'
        ]

    def get_logo_url(self, obj):
        if obj.logo: return obj.logo.url
        return None

    def get_banner_url(self, obj):
        if obj.banner: return obj.banner.url
        return None

class TiendaLogoSerializer(serializers.ModelSerializer):
    """
    Serializer dedicado para subir/actualizar el LOGO de una Tienda.
    """
    logo_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Tienda
        fields = ['logo', 'logo_url']
        read_only_fields = ['logo_url']
    
    def get_logo_url(self, obj):
        if obj.logo:
            return obj.logo.url
        return None
    
    def to_representation(self, instance):
        """Transforma la respuesta para devolver solo la URL"""
        data = super().to_representation(instance)
        data['logo'] = data.get('logo_url')
        return data

class TiendaBannerSerializer(serializers.ModelSerializer):
    """
    Serializer dedicado para subir/actualizar el BANNER de una Tienda.
    """
    banner_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Tienda
        fields = ['banner', 'banner_url']
        read_only_fields = ['banner_url']
    
    def get_banner_url(self, obj):
        if obj.banner:
            return obj.banner.url
        return None
    
    def to_representation(self, instance):
        """Transforma la respuesta para devolver solo la URL"""
        data = super().to_representation(instance)
        data['banner'] = data.get('banner_url')
        return data

class PagoSuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para ver los pagos de suscripción."""
    plan_pagado = PlanSuscripcionSerializer(read_only=True)
    tienda_nombre = serializers.CharField(source='tienda.nombre', read_only=True)
    
    class Meta:
        model = PagoSuscripcion
        fields = [
            'id', 'tienda', 'tienda_nombre', 'plan_pagado', 'monto_total', 
            'fecha_emision', 'fecha_pago', 'estado', 'stripe_payment_intent_id'
        ]
        read_only_fields = fields
