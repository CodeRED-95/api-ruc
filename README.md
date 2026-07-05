# SUNAT RUC API

API profesional en FastAPI para consultar un padrón reducido de RUC de SUNAT con PostgreSQL y Redis.

## Características

- Consulta exacta por RUC
- Búsqueda por razón social con índice de texto
- Filtros por estado, condición y ubigeo
- Paginación y límite por defecto
- Autenticación obligatoria por `X-API-Key`
- Administración por `X-Admin-Key`
- Caché opcional en Redis para consultas por RUC
- Importación masiva con `COPY`
- Swagger automático en `/docs`

## Estructura

```text
sunat-api/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routes/
│   │   └── ruc.py
│   └── services/
│       └── cache.py
├── scripts/
│   └── importar_padron.py
├── sql/
│   └── schema.sql
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Requisitos

- Docker
- Docker Compose
- Archivo TXT/CSV del padrón reducido de SUNAT

## Paso 1. Preparar variables

```bash
cp .env.example .env
```

Ajusta como mínimo:

- `POSTGRES_PASSWORD`
- `API_ADMIN_KEY`
- `HASH_SECRET`

Si quieres, también ajusta:

- `DEFAULT_DAILY_LIMIT`
- `DEFAULT_MINUTE_LIMIT`
- `TOKEN_LENGTH`
- `DEFAULT_PAGE_SIZE`
- `MAX_PAGE_SIZE`

## Paso 2. Levantar PostgreSQL y Redis

```bash
docker compose up -d postgres redis
```

## Paso 3. Crear el esquema

El esquema se carga automáticamente desde `sql/schema.sql` cuando PostgreSQL inicia por primera vez.

Si ya levantaste la base sin esquema, ejecuta:

```bash
docker exec -i sunat-postgres psql -U sunat -d sunat < sql/schema.sql
```

## Paso 4. Importar el padrón

Monta el archivo del padrón dentro del contenedor o ejecútalo localmente con acceso a la misma base.

Ejemplo desde tu máquina:

```bash
python -m pip install -r requirements.txt
set DATABASE_URL=postgresql://sunat:sunat_password@localhost:5432/sunat
python scripts/importar_padron.py C:\ruta\padron.txt
```

En Linux/Debian:

```bash
export DATABASE_URL=postgresql://sunat:sunat_password@localhost:5432/sunat
python3 scripts/importar_padron.py /ruta/padron.txt
```

La importación:

- Limpia filas vacías o mal formateadas
- Usa `COPY`
- Muestra progreso
- Inserta por lotes

## Paso 5. Levantar la API

```bash
docker compose up -d api
```

Swagger:

- `http://localhost:8000/docs`

OpenAPI:

- `http://localhost:8000/openapi.json`

## Endpoints

Todos los endpoints públicos de consulta requieren:

```http
X-API-Key: tu_token
```

Los endpoints administrativos requieren:

```http
X-Admin-Key: tu_clave_admin
```

### GET `/ruc/{ruc}`
Consulta exacta por RUC.

Ejemplo:

```bash
curl http://localhost:8000/ruc/20123456789
```

Ejemplo autenticado:

```bash
curl -H "X-API-Key: TU_API_KEY" http://localhost:8000/ruc/20123456789
```

### Python `requests`

```python
import requests

response = requests.get(
    "http://localhost:8000/ruc/20123456789",
    headers={"X-API-Key": "TU_API_KEY"},
    timeout=30,
)
print(response.status_code)
print(response.json())
```

### JavaScript `fetch`

```javascript
const response = await fetch("http://localhost:8000/ruc/20123456789", {
  headers: {
    "X-API-Key": "TU_API_KEY",
  },
});

const data = await response.json();
console.log(response.status, data);
```

### GET `/buscar?nombre=texto`
Busca por razón social.

Ejemplo:

```bash
curl "http://localhost:8000/buscar?nombre=industria&page=1&page_size=20"
```

### GET `/estado/{estado}`
Lista por estado.

### GET `/condicion/{condicion}`
Lista por condición.

### GET `/ubigeo/{ubigeo}`
Lista por ubigeo.

### GET `/health`
Verifica API y base de datos.

## Respuestas

- `200 OK` consulta exitosa
- `401 Unauthorized` token inválido, ausente o desactivado
- `404 Not Found` RUC no encontrado
- `429 Too Many Requests` límite diario o por minuto excedido
- `500 Internal Server Error` error inesperado

## Endpoints administrativos

- `POST /admin/api-keys`
- `GET /admin/api-keys`
- `GET /admin/api-keys/search?nombre=...`
- `PATCH /admin/api-keys/{id}/activate`
- `PATCH /admin/api-keys/{id}/deactivate`
- `DELETE /admin/api-keys/{id}`
- `POST /admin/api-keys/{id}/regenerate`
- `GET /admin/api-keys/{id}/stats`
- `GET /admin/api-keys/{id}/logs`

## Ejemplo administrativo

```bash
curl -X POST http://localhost:8000/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: TU_ADMIN_KEY" \
  -d '{
    "nombre": "cliente-a",
    "descripcion": "Acceso para cliente A",
    "limite_diario": 5000,
    "limite_por_minuto": 120
  }'
```

## Rendimiento

- `ruc` es clave primaria
- `estado`, `condicion` y `ubigeo` tienen índices B-Tree
- `razon_social` usa `pg_trgm` para búsquedas tipo texto
- Redis puede cachear consultas por RUC
- La API usa pool de conexiones
- Las búsquedas tienen `LIMIT` y `OFFSET`

## Actualizar padrón

Cuando SUNAT publique una nueva versión:

1. Descarga el nuevo archivo
2. Detén la API si lo prefieres, aunque no es obligatorio
3. Ejecuta nuevamente el importador contra el archivo nuevo
4. El script vacía la tabla y recarga el padrón

Si quieres una actualización más segura para producción, puedes adaptar el proceso a:

- Cargar en una tabla temporal
- Validar conteos
- Hacer swap de tablas en una transacción

## Docker en Debian y Portainer

Puedes desplegar este proyecto como stack en Portainer usando el `docker-compose.yml`.

Antes de subirlo:

- crea el archivo `.env`
- asegúrate de montar el archivo del padrón para la importación
- expón solo los puertos que necesites

## Notas importantes

- El importador espera un delimitador `|` por defecto.
- Si tu archivo usa otro delimitador, cambia `PADRON_DELIMITER`.
- `pg_trgm` se crea antes de la tabla al iniciar PostgreSQL por primera vez; si ya existe el volumen, aplica el schema manualmente.
