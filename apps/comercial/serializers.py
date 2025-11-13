from rest_framework import serializers
from .models import (
    Marca, Categoria, LogPrecioProducto, Producto, Foto, 
    Carrito, Detalle_Carrito
)
from apps.saas.models import Tienda

class MarcaSerializer(serializers.ModelSerializer):
    """ Serializer simple para Marcas """
    class Meta:
        model = Marca
        fields = '__all__'
        read_only_fields = ('tienda',)

    def create(self, validated_data):
        validated_data.pop('usuario', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('usuario', None)
        return super().update(instance, validated_data)

class CategoriaSerializer(serializers.ModelSerializer):
    """ Serializer simple para Categorías """
    class Meta:
        model = Categoria
        fields = '__all__'
        read_only_fields = ('tienda',)

    def create(self, validated_data):
        validated_data.pop('usuario', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('usuario', None)
        return super().update(instance, validated_data)

class FotoSerializer(serializers.ModelSerializer):
    """ 
    Serializer para las Fotos de Productos.
    Devuelve la URL completa de la imagen.
    """
    foto_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Foto
        fields = ('id', 'foto', 'foto_url', 'principal', 'producto')
        read_only_fields = ('foto_url',)
        extra_kwargs = {
            'foto': {'write_only': True}
        }

    def get_foto_url(self, obj):
        """ Devuelve la URL completa de Cloudinary """
        if obj.foto:
            request = self.context.get('request', None)
            if request:
                return request.build_absolute_uri(obj.foto.url)
            return obj.foto.url
        return None

    def to_representation(self, instance):
        """ Limpia la respuesta. """
        data = super().to_representation(instance)
        data['foto'] = data.get('foto_url')
        del data['foto_url'] 
        if 'producto' in data and self.parent: 
             del data['producto']
        return data


class LogPrecioProductoSerializer(serializers.ModelSerializer):
    """ Serializer de solo lectura para el historial de precios """
    producto = serializers.StringRelatedField()
    usuario_que_modifico = serializers.StringRelatedField()

    class Meta:
        model = LogPrecioProducto
        fields = '__all__'


# --- Serializers de Producto (Lectura y Escritura) ---

class ProductoSerializer(serializers.ModelSerializer):
    """
    Serializer principal para el modelo Producto.
    Maneja la lectura (con objetos anidados) y la escritura (con IDs).
    """
    
    marca = MarcaSerializer(read_only=True)
    categorias = CategoriaSerializer(many=True, read_only=True)
    fotos = FotoSerializer(many=True, read_only=True)
    tienda = serializers.StringRelatedField(read_only=True)

    marca_id = serializers.PrimaryKeyRelatedField(
        queryset=Marca.objects.all(), 
        source='marca', 
        write_only=True,
        required=False,
        allow_null=True
    )
    categoria_ids = serializers.PrimaryKeyRelatedField(
        queryset=Categoria.objects.all(), 
        source='categorias', 
        many=True, 
        write_only=True,
        required=False
    )

    class Meta:
        model = Producto
        fields = (
            'id', 'nombre', 'descripcion', 'precio', 'stock', 'codigo_referencia', 
            'estado', 'tienda', 'marca', 'categorias', 'fotos', 
            'marca_id', 'categoria_ids'
        )
        read_only_fields = ('tienda',) 
    
    def __init__(self, *args, **kwargs):
        """
        Filtra los querysets de marca_id y categoria_ids
        para que solo muestren opciones de la tienda actual.
        """
        super().__init__(*args, **kwargs)
        
        tienda = self.context.get('tienda', None)
        
        if tienda:
            self.fields['marca_id'].queryset = Marca.objects.filter(tienda=tienda)
            self.fields['categoria_ids'].queryset = Categoria.objects.filter(tienda=tienda)

    def create(self, validated_data):
        validated_data.pop('usuario', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Pasa el 'usuario' al método .save() del modelo
        para la auditoría de precios.
        """
        # Sacamos el usuario para el log
        usuario_para_log = validated_data.pop('usuario', None)
        
        # Sacamos los campos M2M (categorias)
        categorias = validated_data.pop('categorias', None)

        # Actualizamos los campos directos en la instancia
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # ¡Llamamos a .save() CON el usuario!
        # Esto dispara el log de precios en el modelo
        instance.save(usuario=usuario_para_log)

        # Actualizamos los campos M2M si vinieron
        if categorias is not None:
            instance.categorias.set(categorias)
            
        return instance

class ProductoPublicSerializer(serializers.ModelSerializer):
    """
    Serializer específico para vistas PÚBLICAS de productos.
    Solo lectura, sin campos de escritura.
    """
    marca = MarcaSerializer(read_only=True)
    categorias = CategoriaSerializer(many=True, read_only=True)
    fotos = FotoSerializer(many=True, read_only=True)
    tienda = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Producto
        fields = (
            'id', 'nombre', 'descripcion', 'precio', 'stock', 
            'codigo_referencia', 'estado', 'tienda', 'marca', 
            'categorias', 'fotos'
            # Quitamos 'created_at', 'updated_at' ya que no existen en el modelo
        )
        read_only_fields = fields  # Todos los campos son de solo lectura

# --- Serializers de Carrito (Lectura y Escritura) ---

class ProductoSimpleSerializer(serializers.ModelSerializer):
    """
    Serializer súper ligero para mostrar productos
    dentro de los detalles del carrito.
    """
    foto_principal = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = ('id', 'nombre', 'precio', 'foto_principal')

    def get_foto_principal(self, obj):
        """ 
        Obtiene la URL de la foto principal. 
        Reutiliza la lógica de 'get_foto_url' de FotoSerializer.
        """
        foto_obj = obj.fotos.filter(principal=True).first()
        
        if foto_obj and foto_obj.foto:
            request = self.context.get('request', None)
            if request:
                return request.build_absolute_uri(foto_obj.foto.url)
            return foto_obj.foto.url
        return None

class DetalleCarritoSerializer(serializers.ModelSerializer):
    """ Serializer para mostrar los items dentro de un carrito """
    producto = ProductoSimpleSerializer(read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = Detalle_Carrito
        fields = ('id', 'cantidad', 'producto', 'precio_unitario', 'subtotal')
    
    def get_subtotal(self, obj):
        # ¡Usamos el precio_unitario guardado!
        if obj.precio_unitario is not None:
            return obj.cantidad * obj.precio_unitario
        
        # Fallback por si el precio no se guardó (aunque no debería pasar)
        if obj.producto:
            return obj.cantidad * obj.producto.precio
        return 0

class CarritoSerializer(serializers.ModelSerializer):
    """
    Serializer principal para el Carrito.
    Muestra los items anidados y el total (leído desde la BD).
    """
    items = DetalleCarritoSerializer(many=True, read_only=True)

    class Meta:
        model = Carrito
        fields = ('id', 'fecha_creacion', 'cliente', 'tienda', 'total', 'items')
