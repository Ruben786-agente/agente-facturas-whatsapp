# -*- coding: utf-8 -*-
"""
Capa de acceso a la base de datos central (Postgres en producción).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime, Numeric, Date, LargeBinary, ForeignKey,
    BigInteger, UniqueConstraint, Text, Integer, func, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import uuid
log = logging.getLogger("basededatos")
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash

Base = declarative_base()


def _uuid_column(**kwargs):
    return Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), **kwargs)


class Gestoria(Base):
    __tablename__ = "gestorias"
    tenant_id = _uuid_column()
    nombre = Column(String, nullable=False)
    email_contacto = Column(String, nullable=False)
    password_hash = Column(String)
    plan_suscripcion = Column(String, nullable=False, default="trial")
    trial_expira_en = Column(DateTime(timezone=True))
    stripe_customer_id = Column(String)
    stripe_subscription_id = Column(String)
    carpeta_sin_identificar_id = Column(String)
    periodicidad = Column(String, nullable=False, default="mensual", server_default="mensual")  # del Excel: mensual | trimestral
    alta_automatica = Column(Boolean, nullable=False, default=True, server_default="1")  # dar de alta clientes nuevos con la primera factura
    activa = Column(Boolean, nullable=False, default=True)
    creada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    credenciales = relationship("CredencialAlmacenamiento", backref="gestoria")
    empresas = relationship("EmpresaCliente", backref="gestoria")


class NumeroWhatsapp(Base):
    __tablename__ = "numeros_whatsapp"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    phone_number_id = Column(String, nullable=False, unique=True)
    numero_visible = Column(String)
    access_token_cifrado = Column(LargeBinary, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    conectado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CredencialAlmacenamiento(Base):
    __tablename__ = "credenciales_almacenamiento"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    proveedor = Column(String, nullable=False, default="onedrive")
    refresh_token_cifrado = Column(LargeBinary, nullable=False)
    cuenta_conectada = Column(String)
    conectada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EmpresaCliente(Base):
    __tablename__ = "empresas_cliente"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    cif_nif = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    carpeta_raiz_id = Column(String, nullable=False)
    carpeta_facturas_id = Column(String, nullable=False)
    carpeta_tickets_id = Column(String, nullable=False)
    carpeta_revision_id = Column(String, nullable=False)
    carpeta_excel_id = Column(String, nullable=False)
    activa = Column(Boolean, nullable=False, default=True)
    periodicidad = Column(String)   # None = como el resto de la gestoría; o 'mensual' / 'trimestral' / 'unico'
    creada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EstadoSondeo(Base):
    __tablename__ = "estado_sondeo"
    empresa_cliente_id = Column(String(36), ForeignKey("empresas_cliente.id"), primary_key=True)
    ultima_revision = Column(DateTime(timezone=True))


class FacturaCache(Base):
    __tablename__ = "facturas_cache"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    empresa_cliente_id = Column(String(36), ForeignKey("empresas_cliente.id"), nullable=False)
    tipo_documento = Column(String, nullable=False)
    num_factura = Column(String, nullable=False)
    fecha_factura = Column(Date, nullable=False)
    proveedor_cif = Column(String)
    proveedor_nombre = Column(String)
    total_factura = Column(Numeric(12, 2), nullable=False)
    destino = Column(String, nullable=False)
    motivo = Column(String)  # por qué está en Revisión, si aplica
    datos_json = Column(Text)  # lectura de la IA de una factura en Revisión (para poder corregirla desde el panel)
    procesada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProveedorAprendido(Base):
    """CIF que la gestoría confirmó a mano para un proveedor. Cada gestoría tiene los suyos."""
    __tablename__ = "proveedores_aprendidos"
    __table_args__ = (UniqueConstraint("tenant_id", "nombre_norm", name="uq_aprendido_tenant_nombre"),)
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    nombre_norm = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    cif_nif = Column(String, nullable=False)
    veces_usado = Column(Integer, nullable=False, default=0)
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SubidaEstado(Base):
    """Cómo va cada archivo que la gestoría sube desde «Subir facturas» (recibido, leyendo, terminado, con problema...)."""
    __tablename__ = "subidas_estado"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False, index=True)
    nombre = Column(String, nullable=False)              # el que tenía el archivo al subirlo
    nombre_guardado = Column(String, nullable=False)     # el que tiene en «Entrada» (con un código delante)
    estado = Column(String, nullable=False, default="recibido")
    hechos = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    resumen = Column(Text)                               # JSON: cuántas facturas de cada tipo, o un mensaje
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actualizado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CorreoProcesado(Base):
    __tablename__ = "correos_procesados"
    __table_args__ = (UniqueConstraint("tenant_id", "mensaje_id", name="uq_correo_tenant_mensaje"),)
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    mensaje_id = Column(String, nullable=False)
    procesado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CorreoIntento(Base):
    """Cuántas veces ha fallado un correo, para no reintentarlo eternamente."""
    __tablename__ = "correo_intentos"
    __table_args__ = (UniqueConstraint("tenant_id", "mensaje_id", name="uq_intento_tenant_mensaje"),)
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    mensaje_id = Column(String, nullable=False)
    intentos = Column(Integer, nullable=False, default=0)
    ultimo_error = Column(String)
    actualizado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DocumentoVisto(Base):
    """Huella de un documento ya leído: si el correo se reintenta, no se vuelve a pagar a la IA por él."""
    __tablename__ = "documentos_vistos"
    __table_args__ = (UniqueConstraint("tenant_id", "huella", name="uq_visto_tenant_huella"),)
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    huella = Column(String, nullable=False)
    visto_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EstadoCorreo(Base):
    __tablename__ = "estado_correo"
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), primary_key=True)
    ultimo_mensaje_ts = Column(BigInteger)
    error = Column(String)
    actualizado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DocumentoSinIdentificar(Base):
    __tablename__ = "documentos_sin_identificar"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    nombre_archivo = Column(String, nullable=False)
    motivo = Column(String)
    registrado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Aviso(Base):
    __tablename__ = "avisos"
    id = _uuid_column()
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), nullable=False)
    tipo = Column(String, nullable=False)
    mensaje = Column(String, nullable=False)
    visto = Column(Boolean, nullable=False, default=False)
    creado_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


TENANT_GLOBAL = "global"  # para marcas que no son de ninguna gestoría en concreto


class NotificacionEnviada(Base):
    """Registro de correos de aviso ya enviados (para no repetirlos)."""
    __tablename__ = "notificaciones_enviadas"
    id = _uuid_column()
    tenant_id = Column(String(36), nullable=False)
    clave = Column(String, nullable=False)
    enviada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IntentoLogin(Base):
    """Intentos fallidos de entrada, para bloquear un rato a quien prueba contraseñas."""
    __tablename__ = "intentos_login"
    clave = Column(String, primary_key=True)
    fallos = Column(Integer, nullable=False, default=0)
    primero_en = Column(DateTime(timezone=True))
    bloqueado_hasta = Column(DateTime(timezone=True))


class CarpetaEntrada(Base):
    """Carpeta «Entrada» de cada gestoría en su almacenamiento: lo que suba ahí se lee y se archiva solo."""
    __tablename__ = "carpetas_entrada"
    tenant_id = Column(String(36), ForeignKey("gestorias.tenant_id"), primary_key=True)
    proveedor = Column(String, nullable=False)  # los ids solo valen para el almacenamiento que los creó
    entrada_id = Column(String, nullable=False)
    procesados_id = Column(String, nullable=False)
    no_procesables_id = Column(String, nullable=False)


class UsoIAModelo(Base):
    """Consumo de la IA por día y modelo (solo cifras): para saber el coste real por factura."""
    __tablename__ = "uso_ia_modelo"
    dia = Column(String, primary_key=True)      # AAAA-MM-DD
    modelo = Column(String, primary_key=True)
    llamadas = Column(Integer, nullable=False, default=0)
    tokens_entrada = Column(Integer, nullable=False, default=0)
    tokens_salida = Column(Integer, nullable=False, default=0)


class ComparacionModelos(Base):
    """Cuántas veces el modelo barato ha leído lo mismo que el modelo principal (solo contadores)."""
    __tablename__ = "comparacion_modelos"
    dia = Column(String, primary_key=True)
    comparadas = Column(Integer, nullable=False, default=0)
    coinciden = Column(Integer, nullable=False, default=0)


class UsoIA(Base):
    """Consumo de la IA por día (solo cifras, sin datos de nadie): sirve para calcular el coste real por factura."""
    __tablename__ = "uso_ia"
    dia = Column(String, primary_key=True)  # AAAA-MM-DD
    llamadas = Column(Integer, nullable=False, default=0)
    tokens_entrada = Column(Integer, nullable=False, default=0)
    tokens_salida = Column(Integer, nullable=False, default=0)


_engine = None
_Session = None


def _cerrar_api_publica(motor):
    """
    Supabase ofrece además una API pública sobre las tablas. Activar la seguridad por filas (RLS) sin reglas la deja
    cerrada para cualquiera que no sea esta aplicación (que entra con el usuario propietario y no se ve afectada).
    Es idempotente y se aplica también a las tablas nuevas que se creen en el futuro.
    """
    if motor.dialect.name != "postgresql":
        return
    try:
        with motor.begin() as conexion:
            for tabla in Base.metadata.sorted_tables:
                conexion.execute(text(f'ALTER TABLE "{tabla.name}" ENABLE ROW LEVEL SECURITY'))
    except Exception:
        log.exception("No se pudo activar la seguridad por filas en las tablas")


def _anadir_columnas_nuevas(motor):
    """create_all no añade columnas a tablas que ya existen: las que han ido apareciendo se añaden aquí."""
    from sqlalchemy import inspect, text
    try:
        columnas = {c["name"] for c in inspect(motor).get_columns("gestorias")}
        if "periodicidad" not in columnas:
            with motor.begin() as conexion:
                conexion.execute(text("ALTER TABLE gestorias ADD COLUMN periodicidad VARCHAR NOT NULL DEFAULT 'mensual'"))
    except Exception:
        log.exception("No se pudo añadir la columna periodicidad a las gestorías")
    try:
        columnas = {c["name"] for c in inspect(motor).get_columns("gestorias")}
        if "alta_automatica" not in columnas:
            with motor.begin() as conexion:
                conexion.execute(text("ALTER TABLE gestorias ADD COLUMN alta_automatica BOOLEAN NOT NULL DEFAULT TRUE"))
    except Exception:
        log.exception("No se pudo añadir la columna alta_automatica a las gestorías")
    try:
        columnas = {c["name"] for c in inspect(motor).get_columns("empresas_cliente")}
        if "periodicidad" not in columnas:
            with motor.begin() as conexion:
                conexion.execute(text("ALTER TABLE empresas_cliente ADD COLUMN periodicidad VARCHAR"))
    except Exception:
        log.exception("No se pudo añadir la columna periodicidad a los clientes")


def _normalizar_url(url):
    """Arregla los fallos típicos al pegar la dirección de Supabase: espacios o comillas, «postgres://»,
    corchetes alrededor de la contraseña y caracteres especiales (@, #, /, ?) dentro de la contraseña."""
    from urllib.parse import quote, unquote
    url = (url or "").strip().strip("'\"").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if not url.startswith("postgresql://") or "@" not in url:
        return url
    resto = url[len("postgresql://"):]
    credenciales, _, destino = resto.rpartition("@")
    usuario, dos_puntos, clave = credenciales.partition(":")
    if dos_puntos:
        if clave.startswith("[") and clave.endswith("]"):
            clave = clave[1:-1]
        clave = quote(unquote(clave), safe="")
        credenciales = f"{usuario}:{clave}"
    return f"postgresql://{credenciales}@{destino}"


def _obtener_session():
    global _engine, _Session
    if _Session is None:
        # Solo se guarda el resultado si TODO ha ido bien; si la base de datos
        # estaba caída o pausada, la siguiente petición vuelve a intentarlo.
        url = _normalizar_url(os.environ.get("DATABASE_URL", "sqlite:///local_prueba.db"))
        # Sin comprobación previa en cada uso (duplicaba los viajes a la base de datos y hacía lento el panel);
        # en su lugar, las conexiones se renuevan solas cada 4 minutos, antes de que Supabase las cierre por inactividad.
        motor = create_engine(url, pool_pre_ping=False, pool_recycle=240, pool_size=5, max_overflow=5, hide_parameters=True)
        Base.metadata.create_all(motor)
        _anadir_columnas_nuevas(motor)
        _cerrar_api_publica(motor)
        _engine = motor
        _Session = sessionmaker(bind=motor)
    return _Session()


def _fernet():
    clave = os.environ["FERNET_KEY"]
    return Fernet(clave.encode() if isinstance(clave, str) else clave)


def cifrar_refresh_token(token_en_claro: str) -> bytes:
    return _fernet().encrypt(token_en_claro.encode())


def descifrar_refresh_token(token_cifrado: bytes) -> str:
    return _fernet().decrypt(token_cifrado).decode()


def _como_aware_utc(momento):
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


# ---------------------------------------------------------------------------
# Login de la gestoría (panel web)
# ---------------------------------------------------------------------------

def establecer_password(tenant_id, password_en_claro):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        g.password_hash = generate_password_hash(password_en_claro)
        session.commit()
    finally:
        session.close()


def verificar_login(email, password_en_claro):
    """Devuelve tenant_id si el email+contraseña son correctos, None si no."""
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter(func.lower(Gestoria.email_contacto) == (email or "").strip().lower()).first()
        if not g or not g.password_hash:
            return None
        if check_password_hash(g.password_hash, password_en_claro):
            return g.tenant_id
        return None
    finally:
        session.close()


def login_bloqueado(clave):
    """Segundos que faltan para poder volver a intentarlo (0 si no está bloqueado)."""
    session = _obtener_session()
    try:
        r = session.get(IntentoLogin, clave)
        if r and r.bloqueado_hasta:
            falta = (_como_aware_utc(r.bloqueado_hasta) - datetime.now(timezone.utc)).total_seconds()
            return int(falta) if falta > 0 else 0
        return 0
    finally:
        session.close()


def registrar_fallo_login(clave, maximo=8, ventana_min=15, bloqueo_min=15):
    """Cuenta un intento fallido; al llegar al máximo dentro de la ventana, bloquea esa clave unos minutos."""
    session = _obtener_session()
    try:
        ahora = datetime.now(timezone.utc)
        r = session.get(IntentoLogin, clave)
        if r is None:
            r = IntentoLogin(clave=clave, fallos=0, primero_en=ahora)
            session.add(r)
        if r.primero_en is None or _como_aware_utc(r.primero_en) < ahora - timedelta(minutes=ventana_min):
            r.fallos, r.primero_en = 0, ahora
        r.fallos = (r.fallos or 0) + 1
        if r.fallos >= maximo:
            r.bloqueado_hasta = ahora + timedelta(minutes=bloqueo_min)
            r.fallos, r.primero_en = 0, ahora
        session.commit()
    finally:
        session.close()


def limpiar_fallos_login(clave):
    session = _obtener_session()
    try:
        r = session.get(IntentoLogin, clave)
        if r:
            session.delete(r)
            session.commit()
    finally:
        session.close()


def obtener_suscripcion_stripe(tenant_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        return g.stripe_subscription_id if g else None
    finally:
        session.close()


def eliminar_gestoria(tenant_id):
    """Borra la gestoría y TODOS sus datos (empresas, facturas, avisos, conexiones...). No toca sus archivos en OneDrive/Drive."""
    session = _obtener_session()
    try:
        ids_empresas = [e.id for e in session.query(EmpresaCliente.id).filter_by(tenant_id=tenant_id)]
        if ids_empresas:
            session.query(EstadoSondeo).filter(EstadoSondeo.empresa_cliente_id.in_(ids_empresas)).delete(synchronize_session=False)
        for modelo in (FacturaCache, CorreoProcesado, CorreoIntento, DocumentoVisto, EstadoCorreo,
                       DocumentoSinIdentificar, Aviso, NotificacionEnviada, NumeroWhatsapp,
                       CredencialAlmacenamiento, CarpetaEntrada, EmpresaCliente):
            session.query(modelo).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        session.query(Gestoria).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tenants / empresas-cliente / sondeo
# ---------------------------------------------------------------------------

def obtener_tenants_activos():
    session = _obtener_session()
    try:
        filas = (
            session.query(EmpresaCliente, Gestoria, CredencialAlmacenamiento, EstadoSondeo)
            .join(Gestoria, EmpresaCliente.tenant_id == Gestoria.tenant_id)
            .join(CredencialAlmacenamiento, (CredencialAlmacenamiento.tenant_id == Gestoria.tenant_id) & (CredencialAlmacenamiento.proveedor == "onedrive"))
            .outerjoin(EstadoSondeo, EstadoSondeo.empresa_cliente_id == EmpresaCliente.id)
            .filter(
                EmpresaCliente.activa == True, Gestoria.activa == True,  # noqa: E712
                (Gestoria.plan_suscripcion == "activo")
                | ((Gestoria.plan_suscripcion == "trial") & (Gestoria.trial_expira_en > datetime.now(timezone.utc))),
            )
            .all()
        )
        resultado = []
        for empresa, gestoria, credencial, estado in filas:
            resultado.append({
                "tenant_id": gestoria.tenant_id,
                "cif_empresa_cliente": empresa.cif_nif,
                "nombre_empresa": empresa.nombre,
                "refresh_token": descifrar_refresh_token(credencial.refresh_token_cifrado),
                "carpeta_facturas_id": empresa.carpeta_facturas_id,
                "carpeta_tickets_id": empresa.carpeta_tickets_id,
                "carpeta_revision_id": empresa.carpeta_revision_id,
                "carpeta_excel_id": empresa.carpeta_excel_id,
                "ultima_revision_iso": estado.ultima_revision.isoformat() if estado and estado.ultima_revision else None,
                "_empresa_cliente_id": empresa.id,
            })
        return resultado
    finally:
        session.close()


def obtener_facturas_ya_registradas(tenant_id, cif_empresa_cliente):
    session = _obtener_session()
    try:
        empresa = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=cif_empresa_cliente).first()
        if not empresa:
            return []
        filas = session.query(FacturaCache).filter_by(empresa_cliente_id=empresa.id).all()
        return [
            {
                "tenant_id": tenant_id, "cif_empresa_cliente": cif_empresa_cliente,
                "num_factura": f.num_factura, "fecha_factura": f.fecha_factura.strftime("%d/%m/%Y"),
                "emisor": {"cif_nif": f.proveedor_cif or "", "nombre": f.proveedor_nombre or ""},
                "total_factura": float(f.total_factura), "destino": f.destino,
            }
            for f in filas
        ]
    finally:
        session.close()


def guardar_factura_procesada(tenant_id, cif_empresa_cliente, tipo_documento, num_factura,
                                fecha_factura, proveedor_cif, proveedor_nombre, total_factura, destino, motivo=None,
                                datos_json=None):
    session = _obtener_session()
    try:
        empresa = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=cif_empresa_cliente).first()
        if not empresa:
            raise ValueError(f"Empresa-cliente {cif_empresa_cliente} no encontrada para tenant {tenant_id}")
        entrada = FacturaCache(
            tenant_id=tenant_id, empresa_cliente_id=empresa.id, tipo_documento=tipo_documento,
            num_factura=num_factura, fecha_factura=datetime.strptime(fecha_factura, "%d/%m/%Y").date(),
            proveedor_cif=proveedor_cif, proveedor_nombre=proveedor_nombre,
            total_factura=total_factura, destino=destino, motivo=motivo, datos_json=datos_json,
        )
        session.add(entrada)
        session.commit()
        return entrada.id
    finally:
        session.close()


def actualizar_ultima_revision(empresa_cliente_id, momento=None):
    session = _obtener_session()
    try:
        momento = momento or datetime.now(timezone.utc)
        estado = session.get(EstadoSondeo, empresa_cliente_id)
        if estado:
            estado.ultima_revision = momento
        else:
            session.add(EstadoSondeo(empresa_cliente_id=empresa_cliente_id, ultima_revision=momento))
        session.commit()
    finally:
        session.close()


def purgar_cache_antigua(dias=60):
    session = _obtener_session()
    try:
        limite = datetime.now(timezone.utc) - timedelta(days=dias)
        borradas = session.query(FacturaCache).filter(FacturaCache.procesada_en < limite).delete()
        session.commit()
        return borradas
    finally:
        session.close()


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

def resolver_tenant_por_phone_number_id(phone_number_id):
    session = _obtener_session()
    try:
        numero = session.query(NumeroWhatsapp).filter_by(phone_number_id=phone_number_id, activo=True).first()
        if not numero:
            return None
        return {"tenant_id": numero.tenant_id, "access_token": descifrar_refresh_token(numero.access_token_cifrado)}
    finally:
        session.close()


def resolver_empresa_cliente_por_cif(tenant_id, cifs_candidatos):
    cifs_candidatos = [c.strip().upper() for c in cifs_candidatos if c]
    if not cifs_candidatos:
        return None
    session = _obtener_session()
    try:
        empresa = (
            session.query(EmpresaCliente)
            .filter(EmpresaCliente.tenant_id == tenant_id, EmpresaCliente.cif_nif.in_(cifs_candidatos))
            .filter(EmpresaCliente.activa == True)  # noqa: E712
            .first()
        )
        if not empresa:
            return None
        return {
            "id": empresa.id, "cif_nif": empresa.cif_nif, "nombre": empresa.nombre,
            "carpeta_facturas_id": empresa.carpeta_facturas_id, "carpeta_tickets_id": empresa.carpeta_tickets_id,
            "carpeta_revision_id": empresa.carpeta_revision_id, "carpeta_excel_id": empresa.carpeta_excel_id,
        }
    finally:
        session.close()


def obtener_carpeta_sin_identificar(tenant_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        return g.carpeta_sin_identificar_id if g else None
    finally:
        session.close()


def registrar_empresa_cliente(tenant_id, cif_nif, nombre, carpetas):
    """
    Da de alta una empresa-cliente con los ids de sus carpetas en OneDrive.
    carpetas: dict con raiz, facturas, tickets, revision y excel.
    Es idempotente: si ya existe esa empresa (mismo tenant y CIF) la devuelve
    tal cual, sin duplicarla.
    """
    cif_nif = cif_nif.strip().upper()
    session = _obtener_session()
    try:
        existente = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=cif_nif).first()
        if existente:
            return existente.id
        empresa = EmpresaCliente(
            tenant_id=tenant_id, cif_nif=cif_nif, nombre=nombre.strip(),
            carpeta_raiz_id=carpetas["raiz"], carpeta_facturas_id=carpetas["facturas"],
            carpeta_tickets_id=carpetas["tickets"], carpeta_revision_id=carpetas["revision"],
            carpeta_excel_id=carpetas["excel"],
        )
        session.add(empresa)
        session.commit()
        return empresa.id
    finally:
        session.close()


def guardar_carpeta_sin_identificar(tenant_id, carpeta_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        g.carpeta_sin_identificar_id = carpeta_id
        session.commit()
    finally:
        session.close()


def obtener_refresh_token(tenant_id, proveedor):
    session = _obtener_session()
    try:
        cred = session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id, proveedor=proveedor).first()
        if not cred:
            return None
        try:
            return descifrar_refresh_token(cred.refresh_token_cifrado)
        except InvalidToken:
            # Se guardó con otra clave de cifrado: ya no se puede leer nunca. Se borra para que figure como
            # desconectada y la gestoría pueda volver a conectarla.
            log.warning("Credencial %s de %s ilegible (clave de cifrado distinta): se borra", proveedor, tenant_id)
            session.delete(cred)
            session.commit()
            return None
    finally:
        session.close()


def obtener_refresh_token_onedrive(tenant_id):
    return obtener_refresh_token(tenant_id, "onedrive")


def guardar_credencial(tenant_id, proveedor, refresh_token, cuenta=None):
    """Guarda (o reemplaza) el acceso cifrado de una gestoría a OneDrive o Gmail."""
    session = _obtener_session()
    try:
        cred = session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id, proveedor=proveedor).first()
        if cred is None:
            cred = CredencialAlmacenamiento(tenant_id=tenant_id, proveedor=proveedor)
            session.add(cred)
        cred.refresh_token_cifrado = cifrar_refresh_token(refresh_token)
        cred.cuenta_conectada = cuenta
        if proveedor in ("gmail", "outlook"):
            # Solo un correo a la vez: al conectar uno nuevo se quita el otro.
            otro_correo = "outlook" if proveedor == "gmail" else "gmail"
            viejo_correo = session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id, proveedor=otro_correo).first()
            if viejo_correo is not None:
                session.delete(viejo_correo)
        if proveedor in ("onedrive", "gdrive"):
            # Solo un almacenamiento a la vez: al conectar uno nuevo se quita el otro.
            otro = "gdrive" if proveedor == "onedrive" else "onedrive"
            viejo = session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id, proveedor=otro).first()
            if viejo is not None:
                session.delete(viejo)
                g = session.get(Gestoria, tenant_id)
                if g:
                    g.carpeta_sin_identificar_id = None
        cred.conectada_en = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


def eliminar_credencial(tenant_id, proveedor):
    """Borra el acceso guardado (Gmail, OneDrive o Google Drive). No toca facturas ni archivos ya guardados.
    Devuelve el refresh token en claro (para poder revocarlo) o None si no había nada."""
    session = _obtener_session()
    try:
        cred = session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id, proveedor=proveedor).first()
        if cred is None:
            return None
        try:
            token = descifrar_refresh_token(cred.refresh_token_cifrado)
        except InvalidToken:
            token = None
        session.delete(cred)
        if proveedor in ("onedrive", "gdrive"):
            g = session.get(Gestoria, tenant_id)
            if g:
                g.carpeta_sin_identificar_id = None  # esas carpetas eran del almacenamiento anterior
        if proveedor in ("gmail", "outlook"):
            estado = session.get(EstadoCorreo, tenant_id)
            if estado:
                estado.error = None
        session.commit()
        return token
    finally:
        session.close()


def proveedor_correo_activo(tenant_id):
    """'gmail', 'outlook' o None."""
    return _proveedor_activo(tenant_id, ("gmail", "outlook"))


def proveedor_almacenamiento_activo(tenant_id):
    """'onedrive', 'gdrive' o None. Si por lo que sea hubiera los dos conectados, manda el último que se conectó."""
    return _proveedor_activo(tenant_id, ("onedrive", "gdrive"))


def _proveedor_activo(tenant_id, proveedores):
    session = _obtener_session()
    try:
        creds = session.query(CredencialAlmacenamiento).filter(
            CredencialAlmacenamiento.tenant_id == tenant_id,
            CredencialAlmacenamiento.proveedor.in_(proveedores)).all()
        if not creds:
            return None
        ultima = max(creds, key=lambda c: _como_aware_utc(c.conectada_en) if c.conectada_en else datetime.min.replace(tzinfo=timezone.utc))
        return ultima.proveedor
    finally:
        session.close()


def obtener_empresas_con_carpetas(tenant_id):
    """Empresas-cliente activas de la gestoría con los ids de sus carpetas (para la página Archivos)."""
    session = _obtener_session()
    try:
        return [{"id": e.id, "nombre": e.nombre, "cif_nif": e.cif_nif,
                 "facturas": e.carpeta_facturas_id, "tickets": e.carpeta_tickets_id,
                 "revision": e.carpeta_revision_id, "excel": e.carpeta_excel_id}
                for e in session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, activa=True)
                .order_by(EmpresaCliente.nombre)]
    finally:
        session.close()


def listar_empresas_activas(tenant_id):
    session = _obtener_session()
    try:
        return [{"nombre": e.nombre, "cif_nif": e.cif_nif}
                for e in session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, activa=True)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Canal de correo (Gmail)
# ---------------------------------------------------------------------------

def tenants_con_correo():
    """Gestorías con acceso vigente que tienen correo (Gmail u Outlook) y un almacenamiento (OneDrive o Google Drive) conectados."""
    session = _obtener_session()
    try:
        ahora = datetime.now(timezone.utc)
        resultado = []
        for g in session.query(Gestoria).filter(Gestoria.activa == True).all():  # noqa: E712
            vigente = g.plan_suscripcion == "activo" or (
                g.plan_suscripcion == "trial" and g.trial_expira_en and _como_aware_utc(g.trial_expira_en) > ahora)
            if not vigente:
                continue
            provs = {c.proveedor for c in session.query(CredencialAlmacenamiento).filter_by(tenant_id=g.tenant_id)}
            if ({"gmail", "outlook"} & provs) and ({"onedrive", "gdrive"} & provs):
                resultado.append(g.tenant_id)
        return resultado
    finally:
        session.close()


def obtener_estado_correo(tenant_id):
    session = _obtener_session()
    try:
        e = session.get(EstadoCorreo, tenant_id)
        return {"ultimo_mensaje_ts": e.ultimo_mensaje_ts if e else None, "error": e.error if e else None}
    finally:
        session.close()


def guardar_estado_correo(tenant_id, ultimo_mensaje_ts=None, error=None):
    session = _obtener_session()
    try:
        e = session.get(EstadoCorreo, tenant_id)
        if e is None:
            e = EstadoCorreo(tenant_id=tenant_id)
            session.add(e)
        error_anterior = e.error
        if ultimo_mensaje_ts is not None:
            e.ultimo_mensaje_ts = ultimo_mensaje_ts
        e.error = error
        e.actualizado_en = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()
    if error and error != error_anterior:  # el correo acaba de desconectarse: se avisa por correo
        try:
            from notificaciones import notificar_correo_desconectado
            notificar_correo_desconectado(tenant_id, error)
        except Exception:
            log.exception("No se pudo enviar el aviso de correo desconectado")


def registrar_intento_fallido(tenant_id, mensaje_id, error=""):
    """Suma un intento fallido a este correo y devuelve cuántos lleva."""
    session = _obtener_session()
    try:
        r = session.query(CorreoIntento).filter_by(tenant_id=tenant_id, mensaje_id=mensaje_id).first()
        if r is None:
            r = CorreoIntento(tenant_id=tenant_id, mensaje_id=mensaje_id, intentos=0)
            session.add(r)
        r.intentos = (r.intentos or 0) + 1
        r.ultimo_error = (error or "")[:300]
        r.actualizado_en = datetime.now(timezone.utc)
        session.commit()
        return r.intentos
    finally:
        session.close()


VENTANA_DOCUMENTO_VISTO = timedelta(days=2)


def documento_ya_visto(tenant_id, huella):
    """True si este mismo documento se leyó hace poco (solo vale para evitar repeticiones en reintentos)."""
    session = _obtener_session()
    try:
        r = session.query(DocumentoVisto).filter_by(tenant_id=tenant_id, huella=huella).first()
        return bool(r and r.visto_en and _como_aware_utc(r.visto_en) > datetime.now(timezone.utc) - VENTANA_DOCUMENTO_VISTO)
    finally:
        session.close()


def marcar_documento_visto(tenant_id, huella):
    session = _obtener_session()
    try:
        r = session.query(DocumentoVisto).filter_by(tenant_id=tenant_id, huella=huella).first()
        if r is None:
            session.add(DocumentoVisto(tenant_id=tenant_id, huella=huella))
        else:
            r.visto_en = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


def correo_ya_procesado(tenant_id, mensaje_id):
    session = _obtener_session()
    try:
        return session.query(CorreoProcesado).filter_by(tenant_id=tenant_id, mensaje_id=mensaje_id).first() is not None
    finally:
        session.close()


def marcar_correo_procesado(tenant_id, mensaje_id):
    session = _obtener_session()
    try:
        if not session.query(CorreoProcesado).filter_by(tenant_id=tenant_id, mensaje_id=mensaje_id).first():
            session.add(CorreoProcesado(tenant_id=tenant_id, mensaje_id=mensaje_id))
            session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Suscripción / prueba gratuita
# ---------------------------------------------------------------------------

def crear_gestoria_prueba(nombre, email_contacto, dias_prueba=14):
    session = _obtener_session()
    try:
        gestoria = Gestoria(
            nombre=nombre, email_contacto=email_contacto, plan_suscripcion="trial",
            trial_expira_en=datetime.now(timezone.utc) + timedelta(days=dias_prueba), activa=True,
        )
        session.add(gestoria)
        session.commit()
        return gestoria.tenant_id
    finally:
        session.close()


def tenant_tiene_acceso(tenant_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        if not g or not g.activa:
            return False
        if g.plan_suscripcion == "activo":
            return True
        if g.plan_suscripcion == "trial" and g.trial_expira_en and _como_aware_utc(g.trial_expira_en) > datetime.now(timezone.utc):
            return True
        return False
    finally:
        session.close()


def expirar_pruebas_caducadas():
    session = _obtener_session()
    try:
        ahora = datetime.now(timezone.utc)
        caducadas = session.query(Gestoria).filter(Gestoria.plan_suscripcion == "trial", Gestoria.trial_expira_en < ahora).all()
        for g in caducadas:
            g.plan_suscripcion = "prueba_caducada"
            g.activa = False
        session.commit()
        return [g.tenant_id for g in caducadas]
    finally:
        session.close()


def activar_suscripcion(tenant_id, stripe_customer_id, stripe_subscription_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        g.stripe_customer_id = stripe_customer_id
        g.stripe_subscription_id = stripe_subscription_id
        g.plan_suscripcion = "activo"
        g.activa = True
        session.commit()
    finally:
        session.close()


def desactivar_suscripcion(tenant_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        g.plan_suscripcion = "cancelado"
        g.activa = False
        session.commit()
    finally:
        session.close()


def resolver_tenant_por_stripe_customer_id(stripe_customer_id):
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter_by(stripe_customer_id=stripe_customer_id).first()
        return g.tenant_id if g else None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Panel web: resumen y pendientes
# ---------------------------------------------------------------------------

def _plazo_303(anio, trimestre):
    """Último día habitual para presentar el IVA (modelo 303) de un trimestre."""
    from datetime import date, timedelta
    if trimestre == 4:
        d = date(anio + 1, 1, 30)
    else:
        d = date(anio, {1: 4, 2: 7, 3: 10}[trimestre], 20)
    while d.weekday() >= 5:  # si cae en fin de semana, pasa al lunes
        d += timedelta(days=1)
    return d


def _trimestre_en_plazo(hoy):
    """El trimestre ya terminado cuyo plazo de presentación aún no ha vencido (o None)."""
    candidatos = []
    for anio in (hoy.year - 1, hoy.year):
        for t in (1, 2, 3, 4):
            terminado = (hoy.year, hoy.month) > (anio, t * 3)
            plazo = _plazo_303(anio, t)
            if terminado and plazo >= hoy:
                candidatos.append((plazo, anio, t))
    if not candidatos:
        return None
    plazo, anio, t = min(candidatos)
    return {"anio": anio, "trimestre": t, "plazo": plazo, "dias": (plazo - hoy).days}


MINUTOS_POR_DOCUMENTO = 3  # tiempo que se estima que ahorra cada factura leída y archivada


def obtener_periodicidad(tenant_id):
    """'mensual' o 'trimestral': cada cuánto saca el Excel esta gestoría."""
    from periodo_fiscal import PERIODICIDADES, PERIODICIDAD_POR_DEFECTO
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter_by(tenant_id=tenant_id).first()
        valor = getattr(g, "periodicidad", None) if g else None
        return valor if valor in PERIODICIDADES else PERIODICIDAD_POR_DEFECTO
    finally:
        session.close()


def obtener_periodicidad_cliente(tenant_id, cif_empresa):
    """Lo que tiene elegido ese cliente ('mensual', 'trimestral', 'unico') o None si sigue lo de la gestoría."""
    from periodo_fiscal import PERIODICIDADES
    if not cif_empresa:
        return None
    session = _obtener_session()
    try:
        e = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=cif_empresa.strip().upper()).first()
        valor = e.periodicidad if e else None
        return valor if valor in PERIODICIDADES else None
    finally:
        session.close()


def periodicidad_efectiva(tenant_id, cif_empresa=None):
    return obtener_periodicidad_cliente(tenant_id, cif_empresa) or obtener_periodicidad(tenant_id)


def listar_clientes(tenant_id):
    """Todos los clientes activos de la gestoría, con su ajuste de Excel (para la pantalla Clientes)."""
    session = _obtener_session()
    try:
        return [{"id": e.id, "nombre": e.nombre, "cif_nif": e.cif_nif, "periodicidad": e.periodicidad or ""}
                for e in session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, activa=True).order_by(EmpresaCliente.nombre)]
    finally:
        session.close()


def guardar_periodicidad_cliente(tenant_id, empresa_id, periodicidad):
    """periodicidad '' = como el resto de la gestoría."""
    from periodo_fiscal import PERIODICIDADES
    if periodicidad and periodicidad not in PERIODICIDADES:
        return False
    session = _obtener_session()
    try:
        e = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, id=empresa_id, activa=True).first()
        if not e:
            return False
        e.periodicidad = periodicidad or None
        session.commit()
        return True
    finally:
        session.close()


def quitar_cliente(tenant_id, empresa_id):
    """Quita un cliente de la lista (no borra sus carpetas ni sus archivos, ni su historial). Si vuelve a llegar una factura con
    su CIF como comprador, irá a «Sin identificar» en vez de darlo de alta otra vez. Olvida también los documentos «ya vistos»,
    para poder volver a subir ahora mismo lo que se había leído mal."""
    session = _obtener_session()
    try:
        e = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, id=empresa_id, activa=True).first()
        if not e:
            return None
        e.activa = False
        session.query(DocumentoVisto).filter_by(tenant_id=tenant_id).delete()
        session.commit()
        return e.nombre
    finally:
        session.close()


def reactivar_cliente(tenant_id, cif):
    session = _obtener_session()
    try:
        e = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=(cif or "").strip().upper(), activa=False).first()
        if not e:
            return None
        e.activa = True
        session.commit()
        return e.nombre
    finally:
        session.close()


def cliente_quitado(tenant_id, cif):
    session = _obtener_session()
    try:
        return session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=(cif or "").strip().upper(), activa=False).first() is not None
    finally:
        session.close()


def alta_automatica_activa(tenant_id):
    """True (lo normal) si los clientes nuevos se dan de alta solos con su primera factura."""
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter_by(tenant_id=tenant_id).first()
        valor = getattr(g, "alta_automatica", None) if g else None
        return True if valor is None else bool(valor)
    finally:
        session.close()


def guardar_alta_automatica(tenant_id, activa):
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter_by(tenant_id=tenant_id).first()
        if not g:
            return False
        g.alta_automatica = bool(activa)
        session.commit()
        return True
    finally:
        session.close()


def crear_subida(tenant_id, nombre, nombre_guardado):
    session = _obtener_session()
    try:
        s = SubidaEstado(tenant_id=tenant_id, nombre=nombre[:200], nombre_guardado=nombre_guardado)
        session.add(s)
        session.commit()
        return s.id
    finally:
        session.close()


def actualizar_subida(tenant_id, nombre_guardado, estado=None, hechos=None, total=None, resumen=None):
    """Cambia el estado de una subida (si el archivo no vino de «Subir facturas», no hay nada que cambiar)."""
    session = _obtener_session()
    try:
        s = session.query(SubidaEstado).filter_by(tenant_id=tenant_id, nombre_guardado=nombre_guardado).first()
        if s is None:
            return False
        if estado is not None:
            s.estado = estado
        if hechos is not None:
            s.hechos = hechos
        if total is not None:
            s.total = total
        if resumen is not None:
            s.resumen = resumen
        s.actualizado_en = datetime.now(timezone.utc)
        session.commit()
        return True
    finally:
        session.close()


def listar_subidas(tenant_id, dias=3, limite=40):
    """Subidas recientes de la gestoría, las más nuevas primero."""
    from datetime import timedelta
    session = _obtener_session()
    try:
        desde = datetime.now(timezone.utc) - timedelta(days=dias)
        filas = (session.query(SubidaEstado).filter(SubidaEstado.tenant_id == tenant_id, SubidaEstado.creado_en >= desde)
                 .order_by(SubidaEstado.creado_en.desc()).limit(limite).all())
        return [{"id": s.id, "nombre": s.nombre, "estado": s.estado, "hechos": s.hechos, "total": s.total, "resumen": s.resumen,
                 "creado_en": _como_aware_utc(s.creado_en), "actualizado_en": _como_aware_utc(s.actualizado_en)} for s in filas]
    finally:
        session.close()


def guardar_periodicidad(tenant_id, periodicidad):
    from periodo_fiscal import PERIODICIDADES
    if periodicidad not in PERIODICIDADES:
        return False
    session = _obtener_session()
    try:
        g = session.query(Gestoria).filter_by(tenant_id=tenant_id).first()
        if not g:
            return False
        g.periodicidad = periodicidad
        session.commit()
        return True
    finally:
        session.close()


def _mes_en_foco(hoy):
    """Mes del que se está haciendo el cierre: los primeros días del mes siguen siendo del mes anterior."""
    if hoy.day <= 10:
        return (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    return (hoy.year, hoy.month)


def obtener_resumen_panel(tenant_id, trimestre=None, hoy_fecha=None):
    """
    Para el panel de la gestoría:
      - resumen: cuántos documentos hay en cada estado (de todo el histórico),
      - clientes: una fila por empresa cliente y periodo (mes o trimestre, según la gestoría),
      - atencion: lo que la gestoría tiene que mirar (Revisión y Sin identificar),
      - plazo: (solo gestorías trimestrales) cuenta atrás del modelo 303 y clientes con algo sin revisar,
      - cierre: (solo gestorías mensuales) cómo va el cierre del mes en curso,
      - ahorro: documentos gestionados este mes y tiempo estimado ahorrado.
    'trimestre' es el filtro de periodo elegido (p. ej. "2026-10" en mensual o "2024-T1" en trimestral).
    """
    from datetime import date
    from periodo_fiscal import MESES
    periodicidad = obtener_periodicidad(tenant_id)
    if periodicidad == "unico":
        periodicidad = "mensual"   # un solo Excel por cliente; en el panel las facturas se siguen agrupando por mes
    mensual = periodicidad == "mensual"
    session = _obtener_session()
    try:
        filas = (
            session.query(FacturaCache, EmpresaCliente.nombre, EmpresaCliente.cif_nif)
            .join(EmpresaCliente, FacturaCache.empresa_cliente_id == EmpresaCliente.id)
            .filter(FacturaCache.tenant_id == tenant_id, EmpresaCliente.activa == True)  # noqa: E712
            .order_by(FacturaCache.procesada_en.desc())
            .all()
        )
        resumen = {"PROCESADA": 0, "TICKETS": 0, "REVISION": 0, "SIN_IDENTIFICAR": 0, "REVISADA": 0}
        atencion, grupos = [], {}
        hoy = datetime.now(timezone.utc)
        docs_mes = 0
        for f, nombre_empresa, cif in filas:
            resumen[f.destino] = resumen.get(f.destino, 0) + 1
            if f.destino in ("PROCESADA", "REVISADA"):
                momento = _como_aware_utc(f.procesada_en) if f.procesada_en else None
                if momento and (momento.year, momento.month) == (hoy.year, hoy.month):
                    docs_mes += 1
            anio, mes = f.fecha_factura.year, f.fecha_factura.month
            sub = mes if mensual else (mes - 1) // 3 + 1
            clave = (cif, anio, sub)
            g = grupos.setdefault(clave, {
                "empresa": nombre_empresa, "cif": cif, "anio": anio, "sub": sub,
                "clave": f"{anio}-{sub:02d}" if mensual else f"{anio}-T{sub}",
                "etiqueta": f"{MESES[sub - 1]} {anio}" if mensual else f"{sub}T {anio}",
                "periodo": f"{MESES[sub - 1]} {anio}" if mensual else f"Trimestre {sub} - {anio}",
                "facturas": 0, "total": 0.0, "tickets": 0, "revision": 0, "revisadas": 0,
            })
            if f.destino == "PROCESADA":
                g["facturas"] += 1
                g["total"] += float(f.total_factura)
            elif f.destino == "REVISADA":
                g["revisadas"] += 1
            elif f.destino == "TICKETS":
                g["tickets"] += 1
            elif f.destino == "REVISION":
                g["revision"] += 1
                atencion.append({
                    "id": f.id, "empresa": nombre_empresa, "fecha": f.fecha_factura.strftime("%d/%m/%Y"),
                    "proveedor": f.proveedor_nombre or "(desconocido)", "total": float(f.total_factura),
                    "destino": "REVISION", "motivo": f.motivo, "corregible": bool(f.datos_json),
                })
        sin_id = (session.query(DocumentoSinIdentificar).filter_by(tenant_id=tenant_id)
                  .order_by(DocumentoSinIdentificar.registrado_en.desc()).all())
        resumen["SIN_IDENTIFICAR"] = len(sin_id)
        resumen["ILEGIBLES"] = sum(1 for d in sin_id if d.motivo == MOTIVO_ILEGIBLE)
        for d in sin_id:
            atencion.append({
                "id": d.id, "empresa": "(sin identificar)",
                "fecha": _como_aware_utc(d.registrado_en).strftime("%d/%m/%Y"),
                "proveedor": d.nombre_archivo, "total": None, "destino": "SIN_IDENTIFICAR", "motivo": d.motivo,
                "corregible": False,
            })

        todos = sorted(grupos.values(), key=lambda g: (-g["anio"], -g["sub"], g["empresa"]))
        periodos, vistos = [], set()
        for g in todos:  # de más reciente a más antiguo, sin repetir
            if g["clave"] not in vistos:
                vistos.add(g["clave"])
                periodos.append((g["clave"], g["etiqueta"]))
        hoy_d = hoy_fecha or date.today()
        foco = _mes_en_foco(hoy_d) if mensual else None
        if trimestre:
            clientes = [g for g in todos if g["clave"] == trimestre]
        elif mensual:
            # sin filtro, se enseña el mes en curso (o el último con facturas si en ese no hay ninguna)
            clave_foco = f"{foco[0]}-{foco[1]:02d}"
            clientes = [g for g in todos if g["clave"] == clave_foco] or [g for g in todos if periodos and g["clave"] == periodos[0][0]]
        else:
            clientes = todos
        for g in clientes:
            g["total"] = round(g["total"], 2)
            if g["revision"]:
                g["estado"] = "REVISAR"
            elif g["facturas"] or g["revisadas"]:
                g["estado"] = "LISTO"
            else:
                g["estado"] = "SIN_FACTURAS"

        def _sin_facturas(del_periodo):
            con_facturas = {g["cif"] for g in del_periodo}
            return sorted(e.nombre for e in session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, activa=True)
                          if e.cif_nif not in con_facturas)

        plazo = cierre = None
        if mensual:
            clave_foco = f"{foco[0]}-{foco[1]:02d}"
            del_mes = [g for g in todos if g["clave"] == clave_foco]
            cierre = {"etiqueta": f"{MESES[foco[1] - 1]} {foco[0]}", "clientes": len(del_mes),
                      "con_revision": sum(1 for g in del_mes if g["revision"]),
                      "sin_facturas": _sin_facturas(del_mes)}
        else:
            plazo = _trimestre_en_plazo(hoy_d)
            if plazo:
                del_trim = [g for g in todos if (g["anio"], g["sub"]) == (plazo["anio"], plazo["trimestre"])]
                plazo["clientes"] = len(del_trim)
                plazo["con_revision"] = sum(1 for g in del_trim if g["revision"])
                plazo["sin_facturas"] = _sin_facturas(del_trim)
        minutos = docs_mes * MINUTOS_POR_DOCUMENTO
        ahorro = {"documentos": docs_mes, "minutos_por_doc": MINUTOS_POR_DOCUMENTO,
                  "horas": minutos // 60, "minutos": minutos % 60}
        return {"resumen": resumen, "clientes": clientes, "atencion": atencion[:100],
                "periodos": periodos, "periodo_activo": trimestre or (clientes[0]["clave"] if mensual and clientes else ""),
                "periodicidad": periodicidad, "plazo": plazo, "cierre": cierre, "ahorro": ahorro}
    finally:
        session.close()


def obtener_revision(tenant_id, factura_id):
    """Una factura en Revisión con su empresa y la lectura guardada de la IA (o None)."""
    import json
    session = _obtener_session()
    try:
        f = session.query(FacturaCache).filter_by(id=factura_id, tenant_id=tenant_id).first()
        if not f:
            return None
        e = session.get(EmpresaCliente, f.empresa_cliente_id)
        try:
            datos = json.loads(f.datos_json) if f.datos_json else None
        except ValueError:
            datos = None
        return {
            "id": f.id, "destino": f.destino, "motivo": f.motivo, "datos": datos,
            "empresa": {
                "id": e.id, "cif_nif": e.cif_nif, "nombre": e.nombre,
                "carpeta_facturas_id": e.carpeta_facturas_id, "carpeta_tickets_id": e.carpeta_tickets_id,
                "carpeta_revision_id": e.carpeta_revision_id, "carpeta_excel_id": e.carpeta_excel_id,
            },
        }
    finally:
        session.close()


def marcar_revisada(tenant_id, factura_id):
    """La gestoría ya ha gestionado esta factura por su cuenta: sale de la lista de pendientes."""
    session = _obtener_session()
    try:
        f = session.query(FacturaCache).filter_by(id=factura_id, tenant_id=tenant_id, destino="REVISION").first()
        if not f:
            return False
        f.destino = "REVISADA"
        session.commit()
        return True
    finally:
        session.close()


def obtener_otra_revision(tenant_id, excluir_id=None):
    """Id de otra factura pendiente en Revisión que se pueda corregir (con su lectura guardada), o None."""
    session = _obtener_session()
    try:
        q = session.query(FacturaCache).filter_by(tenant_id=tenant_id, destino="REVISION")
        for f in q.order_by(FacturaCache.id).all():
            if f.id != excluir_id and f.datos_json and '"factura"' in f.datos_json:
                return f.id
        return None
    finally:
        session.close()


def eliminar_factura_cache(tenant_id, factura_id):
    session = _obtener_session()
    try:
        n = session.query(FacturaCache).filter_by(id=factura_id, tenant_id=tenant_id).delete()
        session.commit()
        return n > 0
    finally:
        session.close()


def resolver_sin_identificar(tenant_id, documento_id):
    """Quita un documento de la lista de 'Sin identificar' (ya se ha gestionado a mano)."""
    session = _obtener_session()
    try:
        n = session.query(DocumentoSinIdentificar).filter_by(id=documento_id, tenant_id=tenant_id).delete()
        session.commit()
        return n > 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Alta pública y estado de conexiones
# ---------------------------------------------------------------------------

def existe_email_gestoria(email):
    session = _obtener_session()
    try:
        return session.query(Gestoria).filter_by(email_contacto=email).first() is not None
    finally:
        session.close()


class GestoriaNoExiste(Exception):
    """La sesión del navegador apunta a una gestoría que ya no está en la base de datos."""


def obtener_estado_conexiones(tenant_id):
    """Qué tiene conectado la gestoría y si hay algún aviso que mostrar en el panel."""
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        if g is None:
            raise GestoriaNoExiste(tenant_id)
        provs = {c.proveedor: c.cuenta_conectada for c in session.query(CredencialAlmacenamiento).filter_by(tenant_id=tenant_id)}
        estado_correo = session.get(EstadoCorreo, tenant_id)
        return {
            "nombre": g.nombre,
            "plan": g.plan_suscripcion,
            "trial_expira_en": _como_aware_utc(g.trial_expira_en) if g.trial_expira_en else None,
            "email": g.email_contacto,
            "onedrive": "onedrive" in provs, "onedrive_cuenta": provs.get("onedrive"),
            "gdrive": "gdrive" in provs, "gdrive_cuenta": provs.get("gdrive"),
            "almacenamiento": proveedor_almacenamiento_activo(tenant_id),
            "gmail": "gmail" in provs, "gmail_cuenta": provs.get("gmail"),
            "outlook": "outlook" in provs, "outlook_cuenta": provs.get("outlook"),
            "correo": proveedor_correo_activo(tenant_id), "correo_cuenta": provs.get(proveedor_correo_activo(tenant_id) or ""),
            "gmail_error": estado_correo.error if estado_correo else None,
            "correo_error": estado_correo.error if estado_correo else None,
        }
    finally:
        session.close()


def actualizar_carpetas_empresa(tenant_id, cif_nif, carpetas):
    """Sustituye los ids de carpetas de una empresa (cuando se han recreado en OneDrive)."""
    cif_nif = cif_nif.strip().upper()
    session = _obtener_session()
    try:
        e = session.query(EmpresaCliente).filter_by(tenant_id=tenant_id, cif_nif=cif_nif).first()
        if not e:
            return False
        e.carpeta_raiz_id = carpetas["raiz"]
        e.carpeta_facturas_id = carpetas["facturas"]
        e.carpeta_tickets_id = carpetas["tickets"]
        e.carpeta_revision_id = carpetas["revision"]
        e.carpeta_excel_id = carpetas["excel"]
        session.commit()
        return True
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Avisos para la gestoría (se muestran en el panel hasta que los marca como vistos)
# ---------------------------------------------------------------------------

def crear_aviso(tenant_id, tipo, mensaje):
    """No repite un aviso idéntico que siga sin ver."""
    session = _obtener_session()
    try:
        if session.query(Aviso).filter_by(tenant_id=tenant_id, tipo=tipo, mensaje=mensaje, visto=False).first():
            return False
        session.add(Aviso(tenant_id=tenant_id, tipo=tipo, mensaje=mensaje))
        session.commit()
    finally:
        session.close()
    try:  # además del panel, aviso por correo (si está configurado y no es solo informativo)
        from notificaciones import notificar_aviso
        notificar_aviso(tenant_id, tipo, mensaje)
    except Exception:
        log.exception("No se pudo enviar el aviso por correo")
    return True


def email_de_gestoria(tenant_id):
    session = _obtener_session()
    try:
        g = session.get(Gestoria, tenant_id)
        return g.email_contacto if g and g.activa else None
    finally:
        session.close()


def notificacion_reciente(tenant_id, clave, horas):
    """True si ya se envió un correo con esa clave hace menos de `horas` horas."""
    session = _obtener_session()
    try:
        desde = datetime.now(timezone.utc) - timedelta(hours=horas)
        return session.query(NotificacionEnviada).filter(
            NotificacionEnviada.tenant_id == tenant_id, NotificacionEnviada.clave == clave,
            NotificacionEnviada.enviada_en >= desde).first() is not None
    finally:
        session.close()


def registrar_notificacion(tenant_id, clave):
    session = _obtener_session()
    try:
        session.add(NotificacionEnviada(tenant_id=tenant_id, clave=clave))
        session.commit()
        # limpieza: lo de hace más de 120 días ya no hace falta
        session.query(NotificacionEnviada).filter(
            NotificacionEnviada.enviada_en < datetime.now(timezone.utc) - timedelta(days=120)).delete()
        session.commit()
    finally:
        session.close()


def obtener_avisos(tenant_id):
    session = _obtener_session()
    try:
        filas = session.query(Aviso).filter_by(tenant_id=tenant_id, visto=False).order_by(Aviso.creado_en.desc()).limit(20).all()
        return [{"id": a.id, "tipo": a.tipo, "mensaje": a.mensaje, "creado_en": _como_aware_utc(a.creado_en)} for a in filas]
    finally:
        session.close()


def _nombre_norm(nombre):
    """Nombre de proveedor sin tildes, signos ni formas jurídicas (SL, SA...): «Suministros López, S.L.» = «SUMINISTROS LOPEZ»."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFD", nombre or "").encode("ascii", "ignore").decode().upper().replace(".", "")
    palabras = [p for p in re.findall(r"[A-Z0-9]+", t) if p not in {"SL", "SLU", "SA", "SAU", "SC", "CB", "SLL", "SOCIEDAD", "LIMITADA", "ANONIMA"}]
    return " ".join(palabras)


def aprender_proveedor(tenant_id, nombre, cif_nif):
    """Guarda (o actualiza) el CIF que la gestoría ha confirmado para este proveedor. El último confirmado manda."""
    norm = _nombre_norm(nombre)
    if len(norm) < 4 or not cif_nif:
        return False
    session = _obtener_session()
    try:
        fila = session.query(ProveedorAprendido).filter_by(tenant_id=tenant_id, nombre_norm=norm).first()
        if fila:
            fila.cif_nif, fila.nombre = cif_nif, nombre.strip()
        else:
            session.add(ProveedorAprendido(tenant_id=tenant_id, nombre_norm=norm, nombre=nombre.strip(), cif_nif=cif_nif))
        session.commit()
        return True
    finally:
        session.close()


def buscar_proveedor_aprendido(tenant_id, nombre):
    """CIF aprendido de un proveedor con exactamente este nombre (ya normalizado), o None."""
    norm = _nombre_norm(nombre)
    if len(norm) < 4:
        return None
    session = _obtener_session()
    try:
        fila = session.query(ProveedorAprendido).filter_by(tenant_id=tenant_id, nombre_norm=norm).first()
        if not fila:
            return None
        fila.veces_usado = (fila.veces_usado or 0) + 1
        session.commit()
        return {"cif_nif": fila.cif_nif, "nombre": fila.nombre}
    finally:
        session.close()


def listar_proveedores_aprendidos(tenant_id):
    session = _obtener_session()
    try:
        filas = session.query(ProveedorAprendido).filter_by(tenant_id=tenant_id).order_by(ProveedorAprendido.nombre).all()
        return [{"id": f.id, "nombre": f.nombre, "cif_nif": f.cif_nif, "veces": f.veces_usado or 0} for f in filas]
    finally:
        session.close()


def olvidar_proveedor_aprendido(tenant_id, aprendido_id):
    session = _obtener_session()
    try:
        n = session.query(ProveedorAprendido).filter_by(tenant_id=tenant_id, id=aprendido_id).delete()
        session.commit()
        return bool(n)
    finally:
        session.close()


TIPOS_AVISO_INFORMATIVO = ("empresa_nueva", "cif_aprendido", "emisor_detectado")  # no son un problema: solo informan de algo que ha hecho el agente


def marcar_avisos_vistos(tenant_id, grupo=None):
    """grupo: 'info' (solo los informativos), 'alertas' (solo los que son un problema) o None (todos)."""
    session = _obtener_session()
    try:
        q = session.query(Aviso).filter_by(tenant_id=tenant_id, visto=False)
        if grupo == "info":
            q = q.filter(Aviso.tipo.in_(TIPOS_AVISO_INFORMATIVO))
        elif grupo == "alertas":
            q = q.filter(~Aviso.tipo.in_(TIPOS_AVISO_INFORMATIVO))
        q.update({"visto": True}, synchronize_session=False)
        session.commit()
    finally:
        session.close()


def registrar_sin_identificar(tenant_id, nombre_archivo, motivo):
    """Anota un documento que ha ido a la carpeta «Sin identificar», para que salga en el panel."""
    session = _obtener_session()
    try:
        session.add(DocumentoSinIdentificar(tenant_id=tenant_id, nombre_archivo=nombre_archivo, motivo=motivo))
        session.commit()
    finally:
        session.close()


MOTIVO_ILEGIBLE = "documento ilegible o borroso"


def listar_sin_identificar_ilegibles(tenant_id, limite=300):
    session = _obtener_session()
    try:
        filas = (session.query(DocumentoSinIdentificar).filter_by(tenant_id=tenant_id, motivo=MOTIVO_ILEGIBLE)
                 .order_by(DocumentoSinIdentificar.registrado_en).limit(limite).all())
        return [{"id": d.id, "nombre_archivo": d.nombre_archivo, "motivo": d.motivo} for d in filas]
    finally:
        session.close()


def obtener_sin_identificar(tenant_id, documento_id):
    session = _obtener_session()
    try:
        d = session.query(DocumentoSinIdentificar).filter_by(id=documento_id, tenant_id=tenant_id).first()
        return {"id": d.id, "nombre_archivo": d.nombre_archivo, "motivo": d.motivo} if d else None
    finally:
        session.close()


def registrar_uso_ia(tokens_entrada, tokens_salida, modelo=""):
    """Suma una llamada a la IA al contador del día y del modelo. Nunca debe romper la lectura de una factura."""
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    modelo = modelo or "(sin indicar)"
    for _ in range(2):
        session = _obtener_session()
        try:
            r = session.get(UsoIAModelo, (dia, modelo))
            if r is None:
                r = UsoIAModelo(dia=dia, modelo=modelo, llamadas=0, tokens_entrada=0, tokens_salida=0)
                session.add(r)
            r.llamadas = (r.llamadas or 0) + 1
            r.tokens_entrada = (r.tokens_entrada or 0) + int(tokens_entrada or 0)
            r.tokens_salida = (r.tokens_salida or 0) + int(tokens_salida or 0)
            session.commit()
            return
        except Exception:
            session.rollback()
        finally:
            session.close()


def obtener_uso_ia(dias=30):
    """Filas por día y modelo (lo más reciente primero), incluyendo lo contado antes de distinguir modelos."""
    session = _obtener_session()
    try:
        filas = [{"dia": f.dia, "modelo": f.modelo, "llamadas": f.llamadas, "entrada": f.tokens_entrada, "salida": f.tokens_salida}
                 for f in session.query(UsoIAModelo).all()]
        filas += [{"dia": f.dia, "modelo": "(antes de separar por modelo)", "llamadas": f.llamadas, "entrada": f.tokens_entrada,
                   "salida": f.tokens_salida} for f in session.query(UsoIA).all()]
        dias_ordenados = sorted({f["dia"] for f in filas}, reverse=True)[:dias]
        return sorted([f for f in filas if f["dia"] in dias_ordenados], key=lambda f: (f["dia"], f["modelo"]), reverse=True)
    finally:
        session.close()


def registrar_comparacion(coincide):
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for _ in range(2):
        session = _obtener_session()
        try:
            r = session.get(ComparacionModelos, dia)
            if r is None:
                r = ComparacionModelos(dia=dia, comparadas=0, coinciden=0)
                session.add(r)
            r.comparadas = (r.comparadas or 0) + 1
            r.coinciden = (r.coinciden or 0) + (1 if coincide else 0)
            session.commit()
            return
        except Exception:
            session.rollback()
        finally:
            session.close()


def proveedores_conocidos(tenant_id):
    """Proveedores (CIF y nombre) de facturas ya aceptadas de esta gestoría, para corregir un CIF mal leído."""
    session = _obtener_session()
    try:
        filas = (session.query(FacturaCache.proveedor_cif, FacturaCache.proveedor_nombre)
                 .filter(FacturaCache.tenant_id == tenant_id, FacturaCache.destino == "PROCESADA",
                         FacturaCache.proveedor_cif.isnot(None)).distinct().all())
        return [{"cif_nif": c, "nombre": n or ""} for c, n in filas if c]
    finally:
        session.close()


def obtener_motivos_pendientes():
    """Cuántos documentos hay ahora en Revisión o Sin identificar por cada motivo (todas las gestorías, para el titular)."""
    import re
    session = _obtener_session()
    try:
        motivos = [m for (m,) in session.query(FacturaCache.motivo).filter(FacturaCache.destino == "REVISION").all()]
        motivos += [m for (m,) in session.query(DocumentoSinIdentificar.motivo).all()]
        cuenta = {}
        for m in motivos:
            clave = re.sub(r"\s*\([^)]*\)", "", m or "(sin motivo)").strip()
            cuenta[clave] = cuenta.get(clave, 0) + 1
        return sorted(cuenta.items(), key=lambda x: x[1], reverse=True)
    finally:
        session.close()


def obtener_comparacion():
    """(comparadas, coinciden) acumulado de todos los días."""
    session = _obtener_session()
    try:
        filas = session.query(ComparacionModelos).all()
        return sum(f.comparadas for f in filas), sum(f.coinciden for f in filas)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Carpeta de entrada (documentos que la gestoría sube a mano a su almacenamiento)
# ---------------------------------------------------------------------------

def obtener_carpetas_entrada(tenant_id, proveedor):
    """Ids de «Entrada», «Procesados» y «No procesables», o None si no existen o son de otro almacenamiento."""
    session = _obtener_session()
    try:
        c = session.get(CarpetaEntrada, tenant_id)
        if c is None or c.proveedor != proveedor:
            return None
        return {"entrada": c.entrada_id, "procesados": c.procesados_id, "no_procesables": c.no_procesables_id}
    finally:
        session.close()


def guardar_carpetas_entrada(tenant_id, proveedor, entrada, procesados, no_procesables):
    session = _obtener_session()
    try:
        c = session.get(CarpetaEntrada, tenant_id)
        if c is None:
            c = CarpetaEntrada(tenant_id=tenant_id)
            session.add(c)
        c.proveedor, c.entrada_id, c.procesados_id, c.no_procesables_id = proveedor, entrada, procesados, no_procesables
        session.commit()
    finally:
        session.close()


def olvidar_carpetas_entrada(tenant_id):
    session = _obtener_session()
    try:
        session.query(CarpetaEntrada).filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


def tenants_con_almacenamiento():
    """Gestorías con acceso vigente (prueba o suscripción) y un almacenamiento conectado."""
    session = _obtener_session()
    try:
        ahora = datetime.now(timezone.utc)
        resultado = []
        for g in session.query(Gestoria).filter(Gestoria.activa == True).all():  # noqa: E712
            vigente = g.plan_suscripcion == "activo" or (
                g.plan_suscripcion == "trial" and g.trial_expira_en and _como_aware_utc(g.trial_expira_en) > ahora)
            if not vigente:
                continue
            provs = {c.proveedor for c in session.query(CredencialAlmacenamiento).filter_by(tenant_id=g.tenant_id)}
            if {"onedrive", "gdrive"} & provs:
                resultado.append(g.tenant_id)
        return resultado
    finally:
        session.close()
