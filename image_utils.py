"""
Procesamiento de fotografías con OpenCV.

Valida que la imagen recibida contenga al menos un rostro, calcula un
encuadre tipo "carnet" alrededor del rostro principal (el de mayor área,
si se detecta más de uno) y produce un JPEG normalizado de 480x640 px,
comprimido para no superar el límite de tamaño que exigen la mayoría de
terminales Hikvision para registros faciales (≈200 KB).
"""

import base64
import os
import cv2
import numpy as np

# Tamaño final de la foto (proporción 3:4, típica de foto tipo carnet)
ANCHO_SALIDA = 480
ALTO_SALIDA = 640

# Límite típico de tamaño de archivo que aceptan los terminales Hikvision
# al subir una foto de enrolamiento facial (FaceDataRecord).
TAMANO_MAX_BYTES = 200 * 1024

# Carga segura del clasificador XML (Busca en la carpeta local 'cascades' o en OpenCV)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_CASCADE = os.path.join(_BASE_DIR, "cascades", "haarcascade_frontalface_default.xml")

if os.path.exists(_LOCAL_CASCADE):
    cascade_path = _LOCAL_CASCADE
else:
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")

_face_cascade = cv2.CascadeClassifier(cascade_path)

# Validación de seguridad: evitar que el clasificador inicie vacío
if _face_cascade.empty():
    raise RuntimeError(
        f"No se pudo cargar el modelo Haar Cascade desde: '{cascade_path}'. "
        "Verifica que la carpeta 'cascades' contenga el archivo 'haarcascade_frontalface_default.xml'."
    )


class RostroNoDetectadoError(Exception):
    """Se lanza cuando OpenCV no encuentra ningún rostro en la imagen."""


def procesar_foto(datos_imagen) -> bytes:
    """
    Función principal del módulo. Recibe los bytes crudos de una imagen
    o una cadena en Base64 desde el navegador, valida la presencia de
    un rostro y devuelve los bytes de un JPEG 480x640 ya recortado y
    comprimido, listo para guardar en disco y exportar.
    """
    # 0) Limpieza previa si los datos vienen en formato Base64 con/sin encabezado Data URL
    if isinstance(datos_imagen, str):
        if "," in datos_imagen:
            datos_imagen = datos_imagen.split(",")[1]
        datos_imagen = base64.b64decode(datos_imagen)
    elif isinstance(datos_imagen, bytes) and datos_imagen.startswith(b"data:image"):
        texto = datos_imagen.decode("utf-8", errors="ignore")
        if "," in texto:
            datos_imagen = base64.b64decode(texto.split(",")[1])

    if not datos_imagen:
        raise ValueError("No se recibieron datos de imagen para procesar.")

    # 1) Convertir los bytes crudos en una matriz de imagen que OpenCV pueda leer
    arreglo = np.frombuffer(datos_imagen, dtype=np.uint8)
    imagen = cv2.imdecode(arreglo, cv2.IMREAD_COLOR)

    if imagen is None:
        raise ValueError("El archivo enviado no es una imagen válida o está dañado.")

    # 2) Pasar a escala de grises y ecualizar el histograma para mejorar el contraste
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    gris = cv2.equalizeHist(gris)

    # 3) Detectar rostros. Devuelve una lista de rectángulos (x, y, w, h).
    rostros = _face_cascade.detectMultiScale(
        gris, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
    )

    if len(rostros) == 0:
        raise RostroNoDetectadoError(
            "No se detectó ningún rostro en la imagen. Verifique la "
            "iluminación y que el rostro esté centrado frente a la cámara."
        )

    # 4) Seleccionar el rostro con mayor área (el más cercano a la cámara)
    x, y, w, h = max(rostros, key=lambda r: r[2] * r[3])

    # 5) Recortar un encuadre tipo carnet alrededor del rostro y redimensionar
    recorte = _recortar_encuadre(imagen, x, y, w, h)
    recorte = cv2.resize(
        recorte, (ANCHO_SALIDA, ALTO_SALIDA), interpolation=cv2.INTER_AREA
    )

    # 6) Codificar a JPEG respetando el límite de tamaño
    return _codificar_jpg_bajo_limite(recorte)


def _recortar_encuadre(imagen: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """
    Calcula un recorte con proporción 3:4 (480x640) centrado en el
    rostro detectado, dejando espacio para cabeza y hombros.
    """
    alto_img, ancho_img = imagen.shape[:2]
    cx, cy = x + w / 2, y + h / 2  # Centro del rostro detectado

    # El rostro ocupa aproximadamente el 55% del alto del recorte final
    alto_recorte = h / 0.55
    ancho_recorte = alto_recorte * (ANCHO_SALIDA / ALTO_SALIDA)

    y_ini = cy - alto_recorte * 0.45
    y_fin = y_ini + alto_recorte
    x_ini = cx - ancho_recorte / 2
    x_fin = x_ini + ancho_recorte

    # Ajustes de bordes para evitar recortar fuera del lienzo de la imagen
    if x_ini < 0:
        x_fin = min(ancho_img, x_fin - x_ini)
        x_ini = 0
    if y_ini < 0:
        y_fin = min(alto_img, y_fin - y_ini)
        y_ini = 0
    if x_fin > ancho_img:
        x_ini = max(0, x_ini - (x_fin - ancho_img))
        x_fin = ancho_img
    if y_fin > alto_img:
        y_ini = max(0, y_ini - (y_fin - alto_img))
        y_fin = alto_img

    x_ini, y_ini = max(0, int(x_ini)), max(0, int(y_ini))
    x_fin, y_fin = min(ancho_img, int(x_fin)), min(alto_img, int(y_fin))

    return imagen[y_ini:y_fin, x_ini:x_fin]


def _codificar_jpg_bajo_limite(imagen: np.ndarray) -> bytes:
    """
    Codifica la imagen a JPEG reduciendo progresivamente la calidad si sobrepasa TAMANO_MAX_BYTES.
    """
    calidad = 92
    buffer = None
    while calidad >= 40:
        ok, buffer = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, calidad])
        if not ok:
            raise ValueError("No fue posible codificar la imagen a JPEG.")
        if len(buffer) <= TAMANO_MAX_BYTES:
            return buffer.tobytes()
        calidad -= 8

    return buffer.tobytes()