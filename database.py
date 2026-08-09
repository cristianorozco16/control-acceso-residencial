"""
Configuración de la base de datos SQLite mediante SQLAlchemy.

Este archivo centraliza la conexión a la base de datos para que el resto
de la aplicación (modelos, rutas) la reutilice sin repetir configuración.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Ruta del archivo SQLite. Se crea automáticamente en la raíz del proyecto
# la primera vez que se ejecuta la app (no hay que crearlo a mano).
DATABASE_URL = "sqlite:///./residentes.db"

# check_same_thread=False es necesario porque FastAPI puede atender
# una misma conexión SQLite desde distintos hilos del worker de Uvicorn.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Fábrica de sesiones: cada request de FastAPI abrirá su propia sesión
# llamando a SessionLocal(). No se comparte una sola sesión global.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Clase base de la que heredan todos los modelos (tablas) del proyecto.
# Se usa en models.py y aquí mismo, en main.py, para crear las tablas.
Base = declarative_base()


def get_db():
    """
    Dependencia de FastAPI: abre una sesión de base de datos por cada
    petición HTTP y garantiza que se cierre al terminar, incluso si la
    ruta lanza un error. Se usa en las rutas como:

        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db  # Se entrega la sesión a la ruta que la solicitó
    finally:
        db.close()  # Se cierra siempre, así la ruta termine bien o con error
