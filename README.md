# Control de Acceso Residencial

Sistema de registro de habitantes con captura facial por webcam, validación
de rostro con OpenCV y exportación de credenciales en un formato compatible
con la ISAPI de terminales Hikvision.

## Estructura del proyecto

```
control-acceso-residencial/
├── main.py              # App FastAPI: rutas HTML + endpoints /api
├── database.py           # Conexión SQLAlchemy a SQLite
├── models.py              # Modelo ORM Habitante
├── image_utils.py         # Detección de rostro y recorte con OpenCV
├── requirements.txt
├── templates/
│   ├── base.html           # Layout común (navegación, Tailwind CDN)
│   ├── registro.html        # Formulario + modal Habeas Data + webcam
│   └── historial.html       # Tabla de registros + búsqueda + export
└── static/
    └── fotos/                # Fotos normalizadas (480x640 JPG)
```

La base de datos SQLite (`residentes.db`) y la carpeta `static/fotos/` se
crean automáticamente la primera vez que se arranca el servidor.

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Ejecución

```bash
uvicorn main:app --reload
```

Luego abra:

- `http://127.0.0.1:8000/` → formulario de registro
- `http://127.0.0.1:8000/historial` → tabla de habitantes + exportación

> La captura de webcam (`getUserMedia`) requiere un contexto seguro. En
> `localhost` funciona sin certificado; para usarlo en otra máquina de la
> red necesitará servir la app por HTTPS.

## Cómo funciona la validación de rostro

`image_utils.py` usa el clasificador Haar Cascade que trae incluido
`opencv-python` (`haarcascade_frontalface_default.xml`). Si no detecta
ningún rostro, el endpoint `/api/registrar` responde `422` con un mensaje
explicativo y no se guarda el registro. Si detecta uno o más, toma el de
mayor área, calcula un encuadre tipo carnet (proporción 3:4) centrado en el
rostro y lo redimensiona a 480x640 px, comprimiendo el JPEG hasta que pese
menos de ~200 KB (límite habitual de los terminales Hikvision para fotos de
enrolamiento facial).

## Exportación a Hikvision (`/api/exportar-hikvision`)

Genera un `.zip` en memoria con:

- `photos/<documento>.jpg` — las fotos normalizadas de cada habitante.
- `usuarios.json` — dos listas, `UserInfo` y `FaceDataRecord`, con los
  nombres de campo de la ISAPI pública de Hikvision:
  - `UserInfo`: `employeeNo`, `name`, `userType`, `Valid` (`enable`,
    `beginTime`, `endTime`), `doorRight`, `RightPlan` — mismo esquema que
    `POST /ISAPI/AccessControl/UserInfo/Record?format=json`.
  - `FaceDataRecord`: `faceLibType` (`blackFD`), `FDID`, `FPID`, `name`,
    `faceURL` — mismo esquema que
    `POST /ISAPI/Intelligent/FDLib/FaceDataRecord?format=json`.

**Importante:** esta ruta arma el paquete de datos, pero no se conecta
directamente al terminal (eso requeriría la IP, credenciales y autenticación
Digest del equipo, fuera del alcance de esta app). Algunos modelos/firmwares
de Hikvision difieren ligeramente en nombres de campo o límites (tamaño de
imagen, longitud de `employeeNo`, etc.); revise la ISAPI de su equipo
específico antes de una carga masiva, o adapte `main.py` para invocar esos
endpoints por HTTP directamente si prefiere una integración en vivo.

## Posibles extensiones

- Endpoint de eliminación/edición de habitantes.
- Autenticación para el panel de administración (`/historial`, exportación).
- Envío directo a la terminal vía ISAPI (HTTP Digest) en lugar de exportar
  el `.zip` para carga manual.
