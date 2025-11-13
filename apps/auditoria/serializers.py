from rest_framework import serializers
from .models import Bitacora
from apps.users.models import User
from apps.saas.models import Tienda
from apps.users.serializers import UserProfileSerializer, RolSerializer 

class BitacoraTiendaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tienda
        fields = ['id', 'nombre']

class BitacoraUserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    rol = RolSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id_usuario', 'email', 'profile', 'rol']

class BitacoraSerializer(serializers.ModelSerializer):
    user = BitacoraUserSerializer(read_only=True)
    tienda = BitacoraTiendaSerializer(read_only=True)

    class Meta:
        model = Bitacora
        fields = ['id', 'user', 'tienda', 'accion', 'ip', 'objeto', 'extra', 'timestamp']
        read_only_fields = fields