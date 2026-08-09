"""
Sistema de Registro de Habitantes y Control de Acceso Residencial
===================================================================

Backend FastAPI que gestiona el registro de habitantes con captura
facial por webcam, valida la presencia de un rostro con OpenCV, recorta
y normaliza la fotografía, persiste todo en SQLite y permite exportar
un paquete (.zip) compatible con la ISAPI de terminales Hikvision
(esquemas UserInfo / FaceDataRecord).

Ejecutar con:
    uvicorn main:app --reload
"""

import json
import re
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from image_utils import RostroNoDetectadoError, procesar_foto
from models import Habitante

# Rutas absolutas del proyecto, para que la app funcione sin importar
# desde qué carpeta se ejecute el comando "uvicorn main:app"
BASE_DIR = Path(__file__).resolve().parent
CARPETA_FOTOS = BASE_DIR / "static" / "fotos"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Código que se ejecuta UNA sola vez al arrancar el servidor (y otra
    al apagarlo, aquí no hace falta nada en el apagado). Reemplaza al
    antiguo @app.on_event("startup") de versiones previas de FastAPI.
    """
    Base.metadata.create_all(bind=engine)  # Crea las tablas si no existen
    CARPETA_FOTOS.mkdir(parents=True, exist_ok=True)  # Crea static/fotos/ si no existe
    yield  # A partir de aquí la app queda corriendo y atendiendo requests


# Instancia principal de la aplicación FastAPI
app = FastAPI(
    title="Control de Acceso Residencial",
    description="Registro de habitantes y exportación a terminales Hikvision",
    lifespan=lifespan,
)

# Sirve archivos estáticos (las fotos guardadas) en /static/...
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Motor de plantillas Jinja2, apunta a la carpeta templates/
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Vistas HTML (páginas que ve el usuario en el navegador)
# ---------------------------------------------------------------------------

@app.get("/")  # o la ruta que tenga asignada tu vista_registro
async def vista_registro(request: Request):
    # ... código previo de tu función ...
    
    return templates.TemplateResponse(
        request=request, 
        name="registro.html"
    )


@app.get("/historial")
async def vista_historial(request: Request, db: Session = Depends(get_db)):
    """Página de historial: tabla con todos los habitantes ya registrados."""
    habitantes = db.query(Habitante).order_by(Habitante.fecha_registro.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="historial.html",
        context={"request": request, "habitantes": habitantes}
    )


# ---------------------------------------------------------------------------
# API (endpoints que consume el JavaScript del frontend)
# ---------------------------------------------------------------------------

def _sanear_documento(documento: str) -> str:
    """
    Limpia el número de documento dejando solo letras, números, guion y
    guion bajo. Es clave para seguridad: ese valor se usa como nombre de
    archivo en disco, y sin esta limpieza alguien podría intentar un
    "path traversal" (por ejemplo enviando "../../etc/passwd" como documento).
    """
    return re.sub(r"[^A-Za-z0-9_-]", "", documento.strip())


@app.post("/api/registrar")
async def registrar_habitante(
    # Form(...) = campo obligatorio proveniente de un <form>/FormData del navegador
    nombre_completo: str = Form(...),
    tipo_documento: str = Form("CC"),
    documento: str = Form(...),
    torre_bloque: str = Form(""),
    apartamento: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    tipo_habitante: str = Form("propietario"),
    consentimiento_datos: bool = Form(False),
    foto: UploadFile = File(...),  # Imagen capturada por la webcam (multipart)
    db: Session = Depends(get_db),
):
    """
    Registra un nuevo habitante: valida los datos, procesa la foto con
    OpenCV, guarda el archivo en disco y crea el registro en la base de
    datos. Devuelve un JSON que el frontend usa para redirigir o mostrar
    el error correspondiente.
    """

    # --- Paso 1: exigir el consentimiento de datos (Habeas Data) ---
    if not consentimiento_datos:
        raise HTTPException(
            status_code=400,
            detail="Debe aceptar el tratamiento de datos personales (Habeas Data) para continuar.",
        )

    # --- Paso 2: validar y limpiar el número de documento ---
    documento_limpio = _sanear_documento(documento)
    if not documento_limpio:
        raise HTTPException(status_code=400, detail="El número de documento no es válido.")

    # --- Paso 3: evitar documentos duplicados (columna unique en la BD) ---
    existente = db.query(Habitante).filter(Habitante.documento == documento_limpio).first()
    if existente:
        raise HTTPException(
            status_code=409,  # 409 Conflict: el recurso ya existe
            detail=f"Ya existe un habitante registrado con el documento {documento_limpio}.",
        )

    # --- Paso 4: leer los bytes de la imagen subida ---
    contenido = await foto.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="No se recibió ninguna imagen.")

    # --- Paso 5: validar rostro y normalizar la foto con OpenCV ---
    try:
        jpg_bytes = procesar_foto(contenido)
    except RostroNoDetectadoError as exc:
        # 422 Unprocessable Entity: la imagen es válida pero no cumple la regla de negocio
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # --- Paso 6: guardar la foto ya procesada en static/fotos/ ---
    nombre_archivo = f"{documento_limpio}.jpg"
    ruta_archivo = CARPETA_FOTOS / nombre_archivo
    ruta_archivo.write_bytes(jpg_bytes)

    # --- Paso 7: crear y guardar el registro en la base de datos ---
    nuevo = Habitante(
        nombre_completo=nombre_completo.strip(),
        tipo_documento=(tipo_documento or "CC").strip(),
        documento=documento_limpio,
        torre_bloque=torre_bloque.strip(),
        apartamento=apartamento.strip(),
        telefono=telefono.strip(),
        email=email.strip(),
        tipo_habitante=(tipo_habitante or "propietario").strip(),
        foto_path=f"/static/fotos/{nombre_archivo}",  # ruta pública, servida por StaticFiles
        consentimiento_datos=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)  # recarga el objeto para traer el "id" autogenerado

    # --- Paso 8: responder al frontend con los datos del nuevo registro ---
    return {
        "ok": True,
        "id": nuevo.id,
        "documento": nuevo.documento,
        "foto_url": nuevo.foto_path,
        "mensaje": "Habitante registrado correctamente.",
    }


@app.get("/api/habitantes")
async def listar_habitantes(q: str = "", db: Session = Depends(get_db)):
    """
    Devuelve la lista de habitantes en JSON. Si llega el parámetro de
    búsqueda "q" (?q=texto), filtra por nombre, documento, apartamento o
    torre/bloque. La usa el JavaScript de historial.html para la búsqueda
    en vivo sin recargar la página.
    """
    consulta = db.query(Habitante)
    if q:
        patron = f"%{q.strip()}%"  # % % = coincidencia parcial (LIKE de SQL)
        consulta = consulta.filter(
            or_(
                Habitante.nombre_completo.ilike(patron),
                Habitante.documento.ilike(patron),
                Habitante.apartamento.ilike(patron),
                Habitante.torre_bloque.ilike(patron),
            )
        )
    habitantes = consulta.order_by(Habitante.fecha_registro.desc()).all()

    # Se convierte cada objeto ORM a un diccionario simple serializable a JSON
    return [
        {
            "id": h.id,
            "nombre_completo": h.nombre_completo,
            "tipo_documento": h.tipo_documento,
            "documento": h.documento,
            "torre_bloque": h.torre_bloque,
            "apartamento": h.apartamento,
            "telefono": h.telefono,
            "email": h.email,
            "tipo_habitante": h.tipo_habitante,
            "foto_path": h.foto_path,
            "fecha_registro": h.fecha_registro.isoformat() if h.fecha_registro else None,
        }
        for h in habitantes
    ]


@app.get("/api/exportar-hikvision")
async def exportar_hikvision(db: Session = Depends(get_db)):
    """
    Genera al vuelo (en memoria, sin crear archivos temporales en disco)
    un ZIP con:
      - photos/<documento>.jpg  -> fotos normalizadas 480x640
      - usuarios.json           -> estructura inspirada en los esquemas
        ISAPI de Hikvision /ISAPI/AccessControl/UserInfo/Record y
        /ISAPI/Intelligent/FDLib/FaceDataRecord (employeeNo, Valid,
        RightPlan, faceLibType, FDID, FPID).

    NOTA: los nombres de campo siguen la documentación pública de la
    ISAPI, pero cada modelo/firmware de terminal puede requerir ajustes
    menores (por ejemplo, el valor de FDID de tu librería de rostros).
    Verifica la ISAPI específica de tu equipo antes de una carga masiva.
    """
    habitantes = db.query(Habitante).order_by(Habitante.documento).all()
    if not habitantes:
        raise HTTPException(status_code=404, detail="No hay habitantes registrados para exportar.")

    # Vigencia de la credencial: desde ahora y por 10 años (ajustable según el caso de uso)
    ahora = datetime.now()
    inicio_vigencia = ahora.strftime("%Y-%m-%dT%H:%M:%S")
    fin_vigencia = f"{ahora.year + 10}-12-31T23:59:59"

    usuarios = []  # Irá en la clave "UserInfo" del JSON final
    rostros = []   # Irá en la clave "FaceDataRecord" del JSON final
    buffer_zip = BytesIO()  # El ZIP se arma en memoria, no en disco

    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for h in habitantes:
            ruta_foto = BASE_DIR / h.foto_path.lstrip("/")
            if not ruta_foto.exists():
                continue  # Foto ausente: se omite ese habitante, no se rompe la exportación completa

            # Agrega la foto física dentro del zip, en la carpeta photos/
            nombre_en_zip = f"photos/{h.documento}.jpg"
            zf.write(ruta_foto, arcname=nombre_en_zip)

            # Entrada tipo "UserInfo" (datos de la persona y su permiso de acceso)
            usuarios.append(
                {
                    "employeeNo": h.documento,  # Hikvision identifica a cada persona por este campo
                    "name": h.nombre_completo,
                    "userType": "normal",
                    "Valid": {
                        "enable": True,
                        "beginTime": inicio_vigencia,
                        "endTime": fin_vigencia,
                        "timeType": "local",
                    },
                    "doorRight": "1",  # Puerta/lector al que tiene acceso
                    "RightPlan": [{"doorNo": 1, "planTemplateNo": "1"}],
                    "customInfo": f"{h.tipo_habitante} - Apto {h.apartamento} - {h.torre_bloque}".strip(" -"),
                }
            )
            # Entrada tipo "FaceDataRecord" (referencia a la foto de rostro)
            rostros.append(
                {
                    "faceLibType": "blackFD",  # Librería de rostros "permitidos" en Hikvision
                    "FDID": "1",
                    "FPID": h.documento,  # Vincula este rostro con el employeeNo de arriba
                    "name": h.nombre_completo,
                    "faceURL": nombre_en_zip,
                }
            )

        # Se agrega el JSON como un archivo de texto dentro del mismo zip
        contenido_json = {
            "generado": ahora.isoformat(),
            "total_habitantes": len(usuarios),
            "UserInfo": usuarios,
            "FaceDataRecord": rostros,
        }
        zf.writestr("usuarios.json", json.dumps(contenido_json, ensure_ascii=False, indent=2))

    buffer_zip.seek(0)  # Volver al inicio del buffer antes de enviarlo como respuesta
    nombre_zip = f"export_hikvision_{ahora.strftime('%Y%m%d_%H%M')}.zip"

    # StreamingResponse permite enviar el archivo sin cargarlo dos veces en memoria
    return StreamingResponse(
        buffer_zip,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nombre_zip}"'},
    )
