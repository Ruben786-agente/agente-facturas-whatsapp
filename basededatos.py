# -*- coding: utf-8 -*-
"""
Capa de acceso a la base de datos central (Postgres en producción).

Implementa exactamente las funciones que sondeo_periodico.py espera:
    - obtener_tenants_activos()
    - obtener_facturas_ya_registradas(tenant_id, cif_empresa_cliente)
    - guardar_factura_procesada(...)          (nuevo -- para registrar en la caché)
    - actualizar_ultima_revision(...)          (nuevo -- para no releer lo mismo)
    - purgar_cache_antigua(dias=60)            (mantenimiento periódico)

Usa DATABASE_URL de entorno, p.ej.:
    postgresql+psycopg2://usuario:password@host:5432/nombre_bd   (producción)
    sqlite:///local_prueba.db                                     (pruebas locales, sin Postgres)

El cifrado del refresh_token se hace aquí con Fernet (cryptography), usando
una clave FERNET_KEY de entorno -- nunca se guarda el refresh_token en claro.
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime, Numeric, Date, LargeBinary, ForeignKey, select, delete
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid
from cryptography.fernet import Fernet

Base = declarative_base()


def _uuid_column(**kwargs):
    # UUID nativo en Postgres; en SQLite (pruebas locales) se guarda como
    # texto de 36 caracteres -- mismo valor, sin perder compatibilidad.
    return Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), **kwargs)


class Gestoria(Base):
    __tablename__ = "gestorias"
    tenant_id = _uuid_column()
    nombre = Column(String, nullable=False)
    email_contacto = Column(String, nullable=False)
    plan_suscripcion = Column(String, nullable=False, default="trial")
    trial_expira_en = Column(DateTime(timezone=True))
    stripe_customer_id = Column(String)
    stripe_subscription_id = Column(String)
    carpeta_sin_identificar_id = Column(String)
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
    procesada_en = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

_engine = None
_Session = None


def _obtener_session():
    global _engine, _Session
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "sqlite:///local_prueba.db")
        _engine = create_engine(url)
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine)
    return _Session()


def _fernet():
    clave = os.environ["FERNET_KEY"]  # generar una vez con Fernet.generate_key() y guardarla como secreto
    return Fernet(clave.encode() if isinstance(clave, str) else clave)


def cifrar_refresh_token(token_en_claro: str) -> bytes:
    return _fernet().encrypt(token_en_claro.encode())


def descifrar_refresh_token(token_cifrado: bytes) -> str:
    return _fernet().decrypt(token_cifrado).decode()


# ---------------------------------------------------------------------------
# Funciones que sondeo_periodico.py necesita
# ---------------------------------------------------------------------------

def obtener_tenants_activos():
    """
    Devuelve una lista de dicts, uno por CADA EMPRESA-CLIENTE activa (no por
    gestoría -- sondeo_periodico.py itera por empresa-cliente, que es la
    unidad real de "una carpeta a vigilar").
    """
    session = _obtener_session()
    try:
        filas = (
            session.query(EmpresaCliente, Gestoria, CredencialAlmacenamiento, EstadoSondeo)
            .join(Gestoria, EmpresaCliente.tenant_id == Gestoria.tenant_id)
            .join(CredencialAlmacenamiento, CredencialAlmacenamiento.tenant_id == Gestoria.tenant_id)
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
                "_empresa_cliente_id": empresa.id,  # uso interno para actualizar_ultima_revision
            })
        return resultado
    finally:
        session.close()


def obtener_facturas_ya_registradas(tenant_id, cif_empresa_cliente):
    """
    Devuelve las facturas en caché de esta empresa-cliente, en el formato que
    espera detector_duplicados.buscar_posible_duplicado.
    """
    session = _obtener_session()
    try:
        empresa = (
            session.query(EmpresaCliente)
            .filter_by(tenant_id=tenant_id, cif_nif=cif_empresa_cliente)
            .first()
        )
        if not empresa:
            return []

        filas = session.query(FacturaCache).filter_by(empresa_cliente_id=empresa.id).all()
        return [
            {
                "tenant_id": tenant_id,
                "cif_empresa_cliente": cif_empresa_cliente,
                "num_factura": f.num_factura,
                "fecha_factura": f.fecha_factura.strftime("%d/%m/%Y"),
                "emisor": {"cif_nif": f.proveedor_cif or "", "nombre": f.proveedor_nombre or ""},
                "total_factura": float(f.total_factura),
            }
            for f in filas
        ]
    finally:
        session.close()


def guardar_factura_procesada(tenant_id, cif_empresa_cliente, tipo_documento, num_factura,
                                fecha_factura, proveedor_cif, proveedor_nombre, total_factura, destino):
    """Registra una factura/ticket en la caché, tras procesarla (para futuras comprobaciones de duplicado)."""
    from datetime import datetime as dt
    session = _obtener_session()
    try:
        empresa = (
            session.query(EmpresaCliente)
            .filter_by(tenant_id=tenant_id, cif_nif=cif_empresa_cliente)
            .first()
        )
        if not empresa:
            raise ValueError(f"Empresa-cliente {cif_empresa_cliente} no encontrada para tenant {tenant_id}")

        entrada = FacturaCache(
            tenant_id=tenant_id, empresa_cliente_id=empresa.id, tipo_documento=tipo_documento,
            num_factura=num_factura, fecha_factura=dt.strptime(fecha_factura, "%d/%m/%Y").date(),
            proveedor_cif=proveedor_cif, proveedor_nombre=proveedor_nombre,
            total_factura=total_factura, destino=destino,
        )
        session.add(entrada)
        session.commit()
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


def obtener_refresh_token_onedrive(tenant_id):
    """Usado por el webhook de WhatsApp: necesita el OneDrive de la gestoría para poder subir el archivo."""
    session = _obtener_session()
    try:
        cred = (
            session.query(CredencialAlmacenamiento)
            .filter_by(tenant_id=tenant_id, proveedor="onedrive")
            .first()
        )
        return descifrar_refresh_token(cred.refresh_token_cifrado) if cred else None
    finally:
        session.close()


def resolver_tenant_por_phone_number_id(phone_number_id):
    """
    Usado por el webhook de WhatsApp: dado el phone_number_id que manda Meta
    en cada notificación, devuelve el tenant_id y el access_token (para poder
    llamar a la API de Media y descargar la imagen/PDF adjunto).
    Devuelve None si el número no está registrado o está desactivado.
    """
    session = _obtener_session()
    try:
        numero = (
            session.query(NumeroWhatsapp)
            .filter_by(phone_number_id=phone_number_id, activo=True)
            .first()
        )
        if not numero:
            return None
        return {
            "tenant_id": numero.tenant_id,
            "access_token": descifrar_refresh_token(numero.access_token_cifrado),
        }
    finally:
        session.close()


def resolver_empresa_cliente_por_cif(tenant_id, cifs_candidatos):
    """
    Usado tras extraer una factura de WhatsApp (canal mezclado, sin carpeta
    dedicada): busca, dentro de las empresas-cliente de ESTE tenant, cuál
    tiene alguno de los CIFs candidatos (típicamente [cif_emisor, cif_destinatario]).
    Devuelve el dict de la empresa-cliente (con sus carpetas) o None si
    ninguno coincide -- en ese caso, el documento va a carpeta_sin_identificar_id
    de la gestoría, no a un cliente concreto.
    """
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
            "carpeta_facturas_id": empresa.carpeta_facturas_id,
            "carpeta_tickets_id": empresa.carpeta_tickets_id,
            "carpeta_revision_id": empresa.carpeta_revision_id,
            "carpeta_excel_id": empresa.carpeta_excel_id,
        }
    finally:
        session.close()


def obtener_carpeta_sin_identificar(tenant_id):
    session = _obtener_session()
    try:
        gestoria = session.get(Gestoria, tenant_id)
        return gestoria.carpeta_sin_identificar_id if gestoria else None
    finally:
        session.close()


def crear_gestoria_prueba(nombre, email_contacto, dias_prueba=14):
    """Alta de una gestoría nueva en modo prueba, sin pasar por Stripe."""
    session = _obtener_session()
    try:
        gestoria = Gestoria(
            nombre=nombre, email_contacto=email_contacto, plan_suscripcion="trial",
            trial_expira_en=datetime.now(timezone.utc) + timedelta(days=dias_prueba),
            activa=True,
        )
        session.add(gestoria)
        session.commit()
        return gestoria.tenant_id
    finally:
        session.close()


def _como_aware_utc(momento):
    """SQLite (solo en pruebas locales) devuelve datetimes sin zona horaria; Postgres sí la conserva."""
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def tenant_tiene_acceso(tenant_id):
    """True si puede seguir usando el sistema: paga, o está dentro de su prueba."""
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
    """
    Mantenimiento periódico (ejecutar, p.ej., una vez al día): corta el acceso
    a las gestorías cuya prueba gratuita ha terminado sin haber contratado.
    """
    session = _obtener_session()
    try:
        ahora = datetime.now(timezone.utc)
        caducadas = (
            session.query(Gestoria)
            .filter(Gestoria.plan_suscripcion == "trial", Gestoria.trial_expira_en < ahora)
            .all()
        )
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
        gestoria = session.get(Gestoria, tenant_id)
        gestoria.stripe_customer_id = stripe_customer_id
        gestoria.stripe_subscription_id = stripe_subscription_id
        gestoria.plan_suscripcion = "activo"
        gestoria.activa = True
        session.commit()
    finally:
        session.close()


def desactivar_suscripcion(tenant_id):
    session = _obtener_session()
    try:
        gestoria = session.get(Gestoria, tenant_id)
        gestoria.plan_suscripcion = "cancelado"
        gestoria.activa = False
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


def purgar_cache_antigua(dias=60):
    """
    Mantenimiento periódico (ejecutar p.ej. una vez a la semana): borra de la
    caché las facturas más antiguas que 'dias'. Pasado ese tiempo ya no tiene
    sentido comparar contra ellas para detectar duplicados -- el dato
    definitivo ya vive en el Excel de la gestoría, no aquí.
    """
    session = _obtener_session()
    try:
        limite = datetime.now(timezone.utc) - timedelta(days=dias)
        borradas = session.query(FacturaCache).filter(FacturaCache.procesada_en < limite).delete()
        session.commit()
        return borradas
    finally:
        session.close()
