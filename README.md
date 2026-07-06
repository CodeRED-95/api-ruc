# SUNAT RUC API

API profesional para consulta del padrón reducido de RUC de SUNAT con FastAPI, PostgreSQL, Redis, Docker Compose, autenticación por API Key y una interfaz web simple para consulta y administración.

## URLs

- API docs: `http://localhost:8001/docs`
- Web de consulta: `http://localhost:8001/web`
- Admin web: `http://localhost:8001/admin-web`
- pgAdmin: `http://localhost:8081`

## Características

- Consulta exacta por RUC
- Búsqueda por razón social
- Filtros por estado, condición y ubigeo
- Paginación y límite de resultados
- Autenticación obligatoria con `X-API-Key`
- Administración con `X-Admin-Key`
- Caché opcional en Redis para consultas por RUC
- Importación masiva optimizada con `COPY` y staging
- Interfaz web ligera sin frameworks pesados
- Despliegue con Docker Compose

## Estructura

```text
sunat-api/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── web.py
│   ├── routes/
│   │   ├── admin.py
│   │   └── ruc.py
│   ├── services/
│   │   ├── auth.py
│   │   ├── cache.py
│   │   └── logging.py
│   ├── static/
│   │   ├── styles.css
│   │   ├── web.js
│   │   └── admin-web.js
│   └── templates/
│       ├── web.html
│       └── admin_web.html
├── scripts/
│   ├── importar_padron.py
│   └── importar_padron_fast.py
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
- Archivo del padrón reducido de SUNAT, por ejemplo `data/padron.txt`

## 1. Clonar el repositorio

```bash
git clone https://github.com/CodeRED-95/api-ruc.git
cd api-ruc
```

## 2. Crear el archivo `.env`

```bash
copy .env.example .env
```

En Linux o Debian:

```bash
cp .env.example .env
```

## 3. Configuración del `.env`

Edita `.env` con valores propios. Ejemplo:

```env
POSTGRES_DB=sunat
POSTGRES_USER=sunat
POSTGRES_PASSWORD=CAMBIA_ESTA_CLAVE

DATABASE_URL=postgresql://sunat:CAMBIA_ESTA_CLAVE@postgres:5432/sunat
REDIS_URL=redis://redis:6379/0
REDIS_ENABLED=true
CACHE_TTL_SECONDS=3600

API_ADMIN_KEY=CLAVE_ADMIN_LARGA_Y_ALEATORIA
HASH_SECRET=SECRETO_LARGO_Y_ALEATORIO

TOKEN_LENGTH=64
DEFAULT_DAILY_LIMIT=1000
DEFAULT_MINUTE_LIMIT=60
DEFAULT_PAGE_SIZE=50
MAX_PAGE_SIZE=200
DB_POOL_MIN_SIZE=5
DB_POOL_MAX_SIZE=20

PADRON_TABLE=padron_ruc
PADRON_DELIMITER=|

IMPORT_BATCH_SIZE=250000
IMPORT_SKIP_ERRORS=true
IMPORT_LOG_ERRORS=true
IMPORT_ENCODING=latin-1
IMPORT_ERRORS_FILE=logs/importacion_padron.log
```

### Recomendaciones

- `API_ADMIN_KEY`: debe ser larga y aleatoria
- `HASH_SECRET`: debe ser distinta de `API_ADMIN_KEY`
- `TOKEN_LENGTH`: usa `64` o más
- `IMPORT_ENCODING`: usa `latin-1` para el padrón SUNAT
- `IMPORT_BATCH_SIZE`: súbelo si tienes suficiente RAM y quieres menos viajes a PostgreSQL
- `REDIS_ENABLED`: deja `true` si quieres usar caché

## 4. Generar secretos

Generar `API_ADMIN_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Generar `HASH_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 5. Levantar Docker Compose

```bash
docker compose up -d --build
```

Servicios:

- API: `8001`
- PostgreSQL: `5432`
- Redis: interno en Docker
- pgAdmin: `8081`
- Importador: opcional, bajo demanda

## 6. Seguridad Docker

- Redis no debe exponerse con `ports`
- PostgreSQL puede mantenerse interno si solo lo usa la API
- pgAdmin debe usarse en red local o detrás de autenticación
- Cambia las contraseñas por defecto antes de producción
- No subas tu `.env` real a GitHub

## 7. Redis y `vm.overcommit_memory`

Redis debe quedar accesible solo dentro de la red Docker:

```env
REDIS_URL=redis://redis:6379/0
```

Si el host Debian muestra advertencias sobre memoria, aplica:

```bash
cat /proc/sys/vm/overcommit_memory
sudo sysctl vm.overcommit_memory=1
echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

Esto evita errores de Redis durante guardado en segundo plano o replicación.

## 8. Verificar servicios

Ver contenedores:

```bash
docker ps
```

Ver configuración final de Compose:

```bash
docker compose config
```

Ver logs de Redis:

```bash
docker logs sunat-redis --tail=100
```

Redis no debe aparecer publicado como:

```text
0.0.0.0:6379->6379/tcp
```

## 9. Subir el padrón

Copia el archivo a:

```text
./data/padron.txt
```

Ese volumen se monta dentro del contenedor en:

```text
/app/data/padron.txt
```

## 10. Importación rápida en segundo plano

La importación grande debe ejecutarse con el contenedor `importer`, no dejando una terminal abierta.

### Iniciar importación

```bash
docker compose up -d importer
```

O una sola vez:

```bash
docker compose run --rm importer
```

### Forzar importación

```bash
docker compose run --rm -e IMPORT_FORCE=true importer
```

O:

```bash
docker compose run --rm importer python scripts/importar_padron_fast.py /app/data/padron.txt --force
```

### Ver progreso

```bash
docker logs -f sunat-importer
```

### Detener importación

```bash
docker stop sunat-importer
```

### Reiniciar desde cero

1. Detén el importador si está corriendo

```bash
docker stop sunat-importer
```

2. Limpia staging si quedó una ejecución previa

```bash
docker compose exec postgres psql -U sunat -d sunat -c "DROP TABLE IF EXISTS padron_ruc_staging;"
```

3. Vuelve a lanzar la importación

```bash
docker compose up -d importer
```

### Limpiar staging manualmente

```bash
docker compose exec postgres psql -U sunat -d sunat -c "DROP TABLE IF EXISTS padron_ruc_staging;"
```

### Ver conteo final

```bash
docker exec -it sunat-postgres psql -U sunat -d sunat
```

Dentro de `psql`:

```sql
SELECT COUNT(*) FROM padron_ruc;
```

### Ver historial de importaciones

```sql
SELECT * FROM import_history ORDER BY created_at DESC;
```

### Ver últimas importaciones completadas

```sql
SELECT file_name, file_size, status, rows_imported, import_finished_at
FROM import_history
ORDER BY created_at DESC
LIMIT 5;
```

## 11. Importador rápido

El script principal para cargas grandes es:

```text
scripts/importar_padron_fast.py
```

Qué hace:

- conecta a PostgreSQL con `DATABASE_URL`
- crea una tabla staging temporal sin índices
- usa `COPY` para cargar rápido
- soporta `latin-1`
- calcula una firma rápida del archivo para evitar reimportaciones idénticas
- ignora columnas extra del archivo
- limpia registros inválidos
- salta RUC inválidos
- inserta solo las columnas necesarias en `padron_ruc`
- crea índices al final
- registra logs en `logs/importacion_padron.log`

### Mapeo real de columnas

El archivo del padrón puede tener más columnas que la tabla final. Este proyecto usa solo:

- `ruc` = columna 1
- `razon_social` = columna 2
- `estado` = columna 3
- `condicion` = columna 4
- `ubigeo` = columna 5
- `direccion` = columna 8 si existe
- `provincia` = columna 9 si existe
- `departamento` = columna 10 si existe
- `distrito` = columna 11 si existe

Las columnas extra se ignoran.

## 12. Variables del importador

```env
IMPORT_BATCH_SIZE=250000
IMPORT_SKIP_ERRORS=true
IMPORT_LOG_ERRORS=true
IMPORT_ENCODING=latin-1
IMPORT_ERRORS_FILE=logs/importacion_padron.log
IMPORT_SIGNATURE_HEAD_BYTES=1048576
IMPORT_SIGNATURE_TAIL_BYTES=1048576
IMPORT_FORCE=false
```

### Notas

- `IMPORT_BATCH_SIZE` controla cuántas filas se envían por lote a PostgreSQL
- `IMPORT_SKIP_ERRORS=true` evita que una línea inválida detenga toda la carga
- `IMPORT_LOG_ERRORS=true` guarda errores en archivo
- `IMPORT_ENCODING=latin-1` es la opción recomendada para el padrón SUNAT
- `IMPORT_SIGNATURE_HEAD_BYTES` y `IMPORT_SIGNATURE_TAIL_BYTES` ajustan la huella rápida del archivo
- `IMPORT_FORCE=true` fuerza la importación aunque el archivo parezca igual

## 13. Revisar errores de importación

Archivo principal:

```text
logs/importacion_padron.log
```

Ver contenido:

```bash
cat logs/importacion_padron.log
```

Cada error registra:

- número de línea
- motivo
- contenido de la línea si es posible

El historial de importación queda guardado en:

```text
import_history
```

Estados disponibles:

- `running`
- `completed`
- `failed`
- `skipped`

## 14. API

### Swagger

```text
http://localhost:8001/docs
```

### Endpoints públicos

- `GET /ruc/{ruc}`
- `GET /buscar?nombre=texto`
- `GET /estado/{estado}`
- `GET /condicion/{condicion}`
- `GET /ubigeo/{ubigeo}`
- `GET /health`

Todos requieren:

```http
X-API-Key: TU_API_KEY
```

También puedes autenticarte con:

```http
Authorization: Bearer TU_API_KEY
```

O con query params:

```text
/ruc/10452159428?apikey=TU_API_KEY
```

o:

```text
/ruc/10452159428?token=TU_API_KEY
```

### Respuestas esperadas

- `200 OK` consulta exitosa
- `401 Unauthorized` token faltante, inválido o desactivado
- `404 Not Found` RUC no encontrado
- `429 Too Many Requests` superó límite diario o por minuto
- `500 Internal Server Error` error inesperado

## 15. Admin API

### Endpoints administrativos

- `POST /admin/tokens`
- `GET /admin/tokens`
- `GET /admin/tokens/{token_id}`
- `PATCH /admin/tokens/{token_id}/disable`
- `PATCH /admin/tokens/{token_id}/enable`
- `DELETE /admin/tokens/{token_id}`
- `POST /admin/tokens/{token_id}/regenerate`
- `GET /admin/tokens/{token_id}/stats`
- `GET /admin/tokens/{token_id}/logs`

Compatibilidad conservada:

- `POST /admin/api-keys`
- `GET /admin/api-keys`
- `GET /admin/api-keys/{api_key_id}`
- `PATCH /admin/api-keys/{api_key_id}/activate`
- `PATCH /admin/api-keys/{api_key_id}/deactivate`
- `DELETE /admin/api-keys/{api_key_id}`
- `POST /admin/api-keys/{api_key_id}/regenerate`
- `GET /admin/api-keys/{api_key_id}/stats`
- `GET /admin/api-keys/{api_key_id}/logs`

Todos requieren:

```http
X-Admin-Key: TU_API_ADMIN_KEY
```

### Generar token desde la API

```bash
curl -X POST http://localhost:8001/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: TU_API_ADMIN_KEY" \
  -d '{
    "nombre": "cliente-a",
    "descripcion": "Token para cliente A",
    "limite_diario": 5000,
    "limite_por_minuto": 120
  }'
```

La API devuelve el token solo una vez.

## 16. Interfaz web

### Consulta

```text
http://localhost:8001/web
```

Permite:

- ingresar `X-API-Key`
- consultar un RUC
- ver el resultado o el error en pantalla

### Administración

```text
http://localhost:8001/admin-web
```

Permite:

- ingresar `API_ADMIN_KEY`
- guardar la clave localmente en el navegador
- generar tokens
- definir límites diario y por minuto
- ver la tabla de tokens
- ver el token completo solo al crearlo y copiarlo desde el diálogo
- activar, desactivar, eliminar y refrescar tokens

## 17. Consultas de ejemplo

### curl

```bash
curl -H "X-API-Key: TU_API_KEY" http://localhost:8001/ruc/20123456789
```

### Python requests

```python
import requests

resp = requests.get(
    "http://localhost:8001/ruc/20123456789",
    headers={"X-API-Key": "TU_API_KEY"},
    timeout=30,
)
print(resp.status_code)
print(resp.json())
```

### JavaScript fetch

```javascript
const response = await fetch("http://localhost:8001/ruc/20123456789", {
  headers: { "X-API-Key": "TU_API_KEY" }
});
console.log(await response.json());
```

## 18. PostgreSQL

### Entrar por terminal

```bash
docker exec -it sunat-postgres psql -U sunat -d sunat
```

### Contar registros

```sql
SELECT COUNT(*) FROM padron_ruc;
```

### pgAdmin

```text
http://localhost:8081
```

Credenciales por defecto:

- Email: `admin@admin.com`
- Password: `admin123`

Conexión interna a PostgreSQL:

- Host: `postgres`
- Puerto: `5432`
- Base: `sunat`
- Usuario: `sunat`
- Password: la de tu `.env`

## 19. Comandos útiles

Ver logs de la API:

```bash
docker logs sunat-api --tail=100
```

Ver logs de Redis:

```bash
docker logs sunat-redis --tail=100
```

Ver configuración resuelta de Docker:

```bash
docker compose config
```

Ver contenedores activos:

```bash
docker ps
```

Comprobar que Redis no está publicado al host:

```text
No debe aparecer 0.0.0.0:6379->6379/tcp
```

## 20. Notas de seguridad

- Redis no debe exponer `ports`
- PostgreSQL no debería exponerse si solo lo usa la API
- pgAdmin debe usarse solo en red local o detrás de autenticación
- Cambia las credenciales por defecto antes de producción
- Nunca subas el `.env` real a GitHub

## 21. Solución para `vm.overcommit_memory`

Si Redis muestra la advertencia de overcommit en Debian:

```bash
cat /proc/sys/vm/overcommit_memory
sudo sysctl vm.overcommit_memory=1
echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

Esto evita errores de Redis durante persistencia o replicación.

## 22. Importación anterior

El proyecto también conserva `scripts/importar_padron.py`, pero para cargas grandes se recomienda usar:

```bash
docker compose up -d importer
```

o:

```bash
docker compose run --rm importer
```

## 23. Flujo recomendado de producción básica

1. Configura `.env`
2. Levanta `postgres`, `redis`, `api`, `pgadmin`
3. Copia `padron.txt` a `./data/padron.txt`
4. Ejecuta el importador `importer`
5. Revisa logs con `docker logs -f sunat-importer`
6. Verifica `SELECT COUNT(*) FROM padron_ruc;`
7. Consume la API en `http://localhost:8001/docs`
