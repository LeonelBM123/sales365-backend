import time
import stripe
from django.db.utils import IntegrityError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.contrib.auth import login
from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from apps.users.utils import get_user_tienda
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser

from .models import PlanSuscripcion, Tienda, PagoSuscripcion, TiendaCliente
from apps.users.models import Administrador, User, UserProfile, Rol
from .serializers import (
    PlanSuscripcionSerializer, TiendaSerializer, PagoSuscripcionSerializer,
    TiendaDetailSerializer, RegistroSerializer,
    TiendaPublicSerializer,
    TiendaLogoSerializer, 
    TiendaBannerSerializer
)
from apps.users.views import IsSuperAdmin
from apps.auditoria.utils import log_action
from config.pagination import CustomPageNumberPagination

stripe.api_key = settings.STRIPE_SECRET_KEY

class PublicTiendaViewSet(mixins.ListModelMixin, 
                          mixins.RetrieveModelMixin, 
                          viewsets.GenericViewSet):
    """
    API PÚBLICA para listar y ver tiendas.
    - Lista todas las tiendas activas (para el Lobby).
    - Recupera una tienda por su 'slug' (para la página de la tienda).
    """
    queryset = Tienda.objects.filter(estado__in=['ACTIVO', 'PRUEBA']).order_by('nombre')
    serializer_class = TiendaPublicSerializer
    permission_classes = [permissions.AllowAny] # Es una vista pública
    
    # Buscamos por slug (ej: /api/public/tiendas/mi-tienda/)
    lookup_field = 'slug'
    
    # Filtros para que el usuario busque
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['rubro'] # /api/public/tiendas/?rubro=Electronica
    search_fields = ['nombre', 'descripcion_corta', 'rubro']
    ordering_fields = ['nombre']

class PlanSuscripcionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = PlanSuscripcion.objects.all().order_by('precio_mensual')
    serializer_class = PlanSuscripcionSerializer
    permission_classes = [permissions.AllowAny]

class TiendaViewSet(viewsets.ModelViewSet):
    queryset = Tienda.objects.all().select_related('plan', 'admin_contacto__profile')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomPageNumberPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['nombre', 'plan__nombre', 'admin_contacto__email']
    
    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']: return TiendaDetailSerializer
        return TiendaSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'upload_logo', 'upload_banner', 'update', 'partial_update']:
            self.permission_classes = [permissions.IsAuthenticated]
        else:
            self.permission_classes = [IsSuperAdmin]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated: return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return self.queryset
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return self.queryset.filter(id=tienda_actual.id)
        return self.queryset.none()
    
    @action(
        detail=True, 
        methods=['post'], 
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload-logo'
    )
    def upload_logo(self, request, pk=None):
        """
        Sube o actualiza el LOGO de la tienda.
        Replica la lógica de upload_my_photo.
        """
        try:
            tienda = self.get_object()
        except Tienda.DoesNotExist:
            return Response({"error": "La tienda no existe."}, status=status.HTTP_404_NOT_FOUND)

        if 'logo' not in request.FILES:
            return Response({"error": "No se proporcionó ninguna imagen (se esperaba el campo 'logo')."}, status=status.HTTP_400_BAD_REQUEST)

        # Borra la foto anterior de Cloudinary antes de subir la nueva
        if tienda.logo:
            tienda.logo.delete(save=False)

        serializer = TiendaLogoSerializer(tienda, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            log_action(
                request=request, 
                accion=f"Actualizó el logo de la tienda {tienda.nombre}", 
                objeto=f"Tienda: {tienda.nombre} (id:{tienda.id})", 
                usuario=request.user
            )
            return Response(
                {
                    "message": "Logo actualizado exitosamente",
                    "logo": serializer.data['logo'] # Devuelve la nueva URL
                }, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(
        detail=True, 
        methods=['post'], 
        parser_classes=[MultiPartParser, FormParser],
        url_path='upload-banner'
    )
    def upload_banner(self, request, pk=None):
        """
        Sube o actualiza el BANNER de la tienda.
        Replica la lógica de upload_my_photo.
        """
        try:
            tienda = self.get_object()
        except Tienda.DoesNotExist:
            return Response({"error": "La tienda no existe."}, status=status.HTTP_404_NOT_FOUND)

        if 'banner' not in request.FILES:
            return Response({"error": "No se proporcionó ninguna imagen (se esperaba el campo 'banner')."}, status=status.HTTP_400_BAD_REQUEST)

        # Borra la foto anterior de Cloudinary antes de subir la nueva
        if tienda.banner:
            tienda.banner.delete(save=False)

        serializer = TiendaBannerSerializer(tienda, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            log_action(
                request=request, 
                accion=f"Actualizó el banner de la tienda {tienda.nombre}", 
                objeto=f"Tienda: {tienda.nombre} (id:{tienda.id})", 
                usuario=request.user
            )
            return Response(
                {
                    "message": "Banner actualizado exitosamente",
                    "banner": serializer.data['banner'] # Devuelve la nueva URL
                }, 
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PagoSuscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PagoSuscripcion.objects.all().select_related('tienda', 'plan_pagado')
    serializer_class = PagoSuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated: return self.queryset.none()
        if user.rol and user.rol.nombre == 'superAdmin': return self.queryset
        
        tienda_actual = get_user_tienda(user)
        if tienda_actual:
            return self.queryset.filter(tienda=tienda_actual)
        return self.queryset.none()

# --- Lógica de Registro y Sesión ---

def _iniciar_sesion_y_crear_respuesta(request, user, log_message):
    """
    Función centralizada que maneja el inicio de sesión, la creación de token,
    el log con un mensaje personalizado y la construcción de la respuesta.
    """
    login(request, user)
    token, _ = Token.objects.get_or_create(user=user)
    
    tienda_actual = get_user_tienda(user)
    # El mensaje completo ahora se construye aquí
    tienda_info = f" en Tienda: {tienda_actual.nombre}" if tienda_actual else ""
    full_log_message = f"{log_message}{tienda_info}"
    log_action(request, full_log_message, f"Usuario: {user.email}", user)

    response_data = {
        'status': 'success', 'token': token.key, 'user_id': user.id_usuario,
        'rol': user.rol.nombre if user.rol else None,
        'tienda_id': tienda_actual.id if tienda_actual else None,
        'nombre_completo': f"{user.profile.nombre} {user.profile.apellido}" if hasattr(user, 'profile') else 'N/A'
    }
    return response_data

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def registro_directo_prueba(request):
    serializer = RegistroSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if User.objects.filter(email=data['admin_email']).exists():
        return Response({"error": "Este correo electrónico ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            plan = PlanSuscripcion.objects.get(pk=data['plan_id'])
            if not plan.dias_prueba > 0:
                return Response({"error": "Este endpoint es solo para planes de prueba."}, status=status.HTTP_400_BAD_REQUEST)
            
            rol_admin, _ = Rol.objects.get_or_create(nombre='admin', defaults={'descripcion': 'Administrador de una tienda.'})
            admin_user = User.objects.create_user(email=data['admin_email'], password=data['admin_password'])
            UserProfile.objects.create(
                user=admin_user,
                nombre=data['admin_nombre'],
                apellido=data['admin_apellido'],
                ci=data['admin_ci'],
                telefono=data.get('admin_telefono', '')
            )
            nueva_tienda = Tienda.objects.create(
                plan=plan, 
                nombre=data['tienda_nombre'], 
                admin_contacto=admin_user,
                slug=data.get('slug'), # Se auto-generará si está vacío
                rubro=data.get('rubro', 'General'),
                descripcion_corta=data.get('descripcion_corta', '')
            )
            Administrador.objects.create(
                user=admin_user,
                tienda=nueva_tienda,
                fecha_contratacion=timezone.now().date()
            )
            admin_user.rol = rol_admin
            admin_user.save()

            log_action(
                request,
                f"Registro de tienda de prueba exitoso en Tienda: {nueva_tienda.nombre}",
                f"Usuario: {admin_user.email}",
                admin_user
            )

            return Response({
                "message": "¡Tienda de prueba creada exitosamente!",
                "tienda_id": nueva_tienda.id,
                "user_id": admin_user.id_usuario
            }, status=status.HTTP_201_CREATED)

    except IntegrityError as e:
        if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
            existing_user = User.objects.filter(email=data['admin_email']).first()
            if existing_user:
                log_action(
                    request,
                    "Intento de creación duplicado detectado, usuario ya existente.",
                    f"Usuario: {existing_user.email}",
                    existing_user
                )
                return Response({
                    "message": "El usuario ya fue registrado recientemente. Puedes iniciar sesión.",
                    "user_id": existing_user.id_usuario
                }, status=status.HTTP_200_OK)
        # otros errores de integridad se propagan normalmente
        raise

    except Exception as e:
        return Response({"error": f"Ocurrió un error inesperado: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def crear_sesion_pago_stripe(request):
    serializer = RegistroSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if User.objects.filter(email=data['admin_email']).exists():
        return Response({"error": "Este correo electrónico ya está en uso."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        plan = PlanSuscripcion.objects.get(pk=data['plan_id'])
        if not plan.stripe_price_id:
            return Response({"error": f"El plan '{plan.nombre}' no tiene un Price ID de Stripe configurado."}, status=500)
        price_id = plan.stripe_price_id
        base_url = settings.FRONTEND_URL.rstrip('/')
        return_url = f"{base_url}/saas-register/return?session_id={{CHECKOUT_SESSION_ID}}"
        session = stripe.checkout.Session.create(
            ui_mode='embedded', customer_email=data['admin_email'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription', return_url=return_url,
            metadata={
                'plan_id': str(plan.id), 
                'tienda_nombre': data['tienda_nombre'],
                'admin_nombre': data['admin_nombre'], 
                'admin_apellido': data['admin_apellido'],
                'admin_ci': data['admin_ci'], 
                'admin_email': data['admin_email'],
                'admin_password': data['admin_password'], 
                'admin_telefono': data.get('admin_telefono', ''),
                
                'slug': data.get('slug', ''),
                'rubro': data.get('rubro', 'General'),
                'descripcion_corta': data.get('descripcion_corta', '')
            }
        )
        return Response({'clientSecret': session.client_secret})
    except Exception as e:
        return Response({"error": f"Error del servidor al crear sesión: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def confirmar_registro_pago(request):
    session_id = request.data.get('session_id')
    if not session_id:
        return Response({"error": "Falta el ID de la sesión."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != 'paid':
            time.sleep(3)
            session = stripe.checkout.Session.retrieve(session_id)
        if not (session.payment_status == 'paid' and session.invoice):
            return Response({"error": "El pago no se pudo confirmar en Stripe."}, status=status.HTTP_400_BAD_REQUEST)
        
        invoice_id = session.invoice
        with transaction.atomic():
            metadata = session.metadata
            rol_admin, _ = Rol.objects.get_or_create(nombre='admin', defaults={'descripcion': 'Administrador de una tienda.'})
            
            admin_user, created = User.objects.get_or_create(
                email=metadata['admin_email'],
                defaults={'password': make_password(metadata['admin_password'])}
            )

            if not created:
                response_data = _iniciar_sesion_y_crear_respuesta(request, admin_user, "Inicio de sesión post-registro de la tienda")
                response_data['message'] = 'El usuario ya fue registrado en una petición anterior.'
                return Response(response_data)
            
            plan = PlanSuscripcion.objects.get(pk=metadata['plan_id'])
            UserProfile.objects.create(
                user=admin_user, 
                nombre=metadata['admin_nombre'], 
                apellido=metadata['admin_apellido'], 
                ci=metadata['admin_ci'], 
                telefono=metadata.get('admin_telefono', '')
            )
            nueva_tienda = Tienda.objects.create(
                plan=plan, 
                nombre=metadata['tienda_nombre'], 
                admin_contacto=admin_user,
                slug=metadata.get('slug'),
                rubro=metadata.get('rubro', 'General'),
                descripcion_corta=metadata.get('descripcion_corta', '')
            )
            Administrador.objects.create(
                user=admin_user, 
                tienda=nueva_tienda, 
                fecha_contratacion=timezone.now().date()
            )
            
            admin_user.rol = rol_admin
            admin_user.save()

            PagoSuscripcion.objects.create(
                tienda=nueva_tienda, plan_pagado=plan,
                stripe_payment_intent_id=invoice_id,
                monto_total=plan.precio_mensual,
                estado='PAGADO', fecha_pago=timezone.now()
            )
            
            tienda_info = f" en Tienda: {nueva_tienda.nombre}"
            log_action(request, f"Se realizó el pago y activación de la tienda{tienda_info}", f"Usuario: {admin_user.email}", admin_user)

            response_data = _iniciar_sesion_y_crear_respuesta(request, admin_user, "Registro de tienda exitoso")
            return Response(response_data)

    except Exception as e:
        return Response({"error": f"Error final al crear la cuenta: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)