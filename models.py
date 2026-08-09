"""
Modelos ORM de la base de datos.

Este archivo define las tablas de la base de datos usando SQLAlchemy.
Cada clase que hereda de "Base" se convierte en una tabla SQL; cada
atributo de la clase se convierte en una columna de esa tabla.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from database import Base


class Habitante(Base):
    """
    Representa a un habitante del conjunto residencial registrado en el
    sistema. Cada fila de esta tabla es una persona con su foto y sus
    datos de contacto/ubicación dentro del conjunto.
    """

    __tablename__ = "habitantes"  # Nombre real de la tabla en SQLite

    # Identificador interno autoincremental (no es el número de documento)
    id = Column(Integer, primary_key=True, index=True)

    # --- Datos de identificación de la persona ---
    nombre_completo = Column(String(150), nullable=False)
    tipo_documento = Column(String(5), nullable=False, default="CC")  # CC, CE, TI, PA, RC
    documento = Column(String(30), unique=True, nullable=False, index=True)  # unique=True evita duplicados

    # --- Ubicación dentro del conjunto residencial ---
    torre_bloque = Column(String(20), nullable=True, default="")
    apartamento = Column(String(20), nullable=False)
    tipo_habitante = Column(String(30), nullable=False, default="propietario")  # propietario/arrendatario/etc.

    # --- Datos de contacto (opcionales, por eso nullable=True) ---
    telefono = Column(String(20), nullable=True, default="")
    email = Column(String(120), nullable=True, default="")

    # --- Foto y consentimiento legal ---
    foto_path = Column(String(255), nullable=False)  # Ruta pública, ej: /static/fotos/123.jpg
    consentimiento_datos = Column(Boolean, nullable=False, default=False)  # Aceptó el Habeas Data

    # Fecha de creación del registro; la asigna automáticamente la base
    # de datos (server_default=func.now()) al insertar la fila.
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
