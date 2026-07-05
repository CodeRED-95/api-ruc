# SUNAT RUC API

API de consulta de RUC con FastAPI, PostgreSQL, Redis, Docker Compose, autenticación por `X-API-Key` y panel web simple para consultas y administración básica.

## URLs

- API docs: `http://localhost:8001/docs`
- Web de consulta: `http://localhost:8001/web`
- Admin web: `http://localhost:8001/admin-web`
- pgAdmin: `http://localhost:8080`

## Estructura principal

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
│   └── importar_padron.py
├── sql/
│   └── schema.sql
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Requisitos

- Docker
- Docker Compose
- Archivo `padron.txt` o equivalente del padrón reducido SUNAT

## 1. Clonar el repo

```bash
git clone https://github.com/CodeRED-95/api-ruc.git
```

## 2. Crear `.env`

```bash
copy .env.example .env
```

En Linux:

```bash
cp .env.example .env
```

## 2.1. Configuración del `.env`

Edita el archivo `.env` con estos valores:

```env
DATABASE_URL=postgresql://sunat:TU_PASSWORD@postgres:5432/sunat
REDIS_URL=redis://redis:6379/0
REDIS_ENABLED=true
CACHE_TTL_SECONDS=3600
API_ADMIN_KEY=TU_CLAVE_ADMIN_LARGA
HASH_SECRET=TU_SECRETO_LARGO_PARA_HASH
TOKEN_LENGTH=64
DEFAULT_DAILY_LIMIT=1000
DEFAULT_MINUTE_LIMIT=60
DEFAULT_PAGE_SIZE=50
MAX_PAGE_SIZE=200
DB_POOL_MIN_SIZE=5
DB_POOL_MAX_SIZE=20
PADRON_TABLE=padron_ruc
PADRON_DELIMITER=|
POSTGRES_DB=sunat
POSTGRES_USER=sunat
POSTGRES_PASSWORD=TU_PASSWORD
```

Valores recomendados:

- `API_ADMIN_KEY`: una cadena larga y aleatoria
- `HASH_SECRET`: una cadena larga y aleatoria distinta de `API_ADMIN_KEY`
- `TOKEN_LENGTH`: `64` o superior
- `DEFAULT_DAILY_LIMIT`: según tu plan de uso
- `DEFAULT_MINUTE_LIMIT`: según tu capacidad de tráfico

Si PostgreSQL corre en el mismo `docker-compose.yml`, normalmente no necesitas cambiar:

- `POSTGRES_DB`
- `POSTGRES_USER`
- `REDIS_URL`

## 3. Generar `API_ADMIN_KEY`

Puedes generar una clave larga con Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 4. Generar `HASH_SECRET`

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Pega ambos valores en `.env`:

- `API_ADMIN_KEY`
- `HASH_SECRET`

## 5. Levantar Docker Compose

```bash
docker compose up -d --build
```

Servicios:

- API: `8001`
- PostgreSQL: `5432`
- Redis: `6379`
- pgAdmin: `8080`

## 6. Probar Swagger

```bash
curl http://localhost:8001/docs
```

O abre:

```text
http://localhost:8001/docs
```

## 7. Subir el padrón

Crea la carpeta local `data` en el proyecto y copia ahí el archivo:

```text
data/padron.txt
```

Ese directorio se monta dentro del contenedor en `/app/data`.

## 8. Importar el padrón

Ejecuta:

```bash
docker compose exec api python scripts/importar_padron.py /app/data/padron.txt
```

El script:

- limpia filas inválidas
- usa `COPY`
- muestra progreso

## 9. Generar tokens

Desde la web admin:

```text
http://localhost:8001/admin-web
```

O por API:

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

La respuesta incluye la API Key generada una sola vez.

## 10. Probar consulta RUC

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

## 11. Usar la web

### Web de consulta

Abre:

```text
http://localhost:8001/web
```

Ingresa:

- tu `X-API-Key`
- el RUC de 11 dígitos

### Admin web

Abre:

```text
http://localhost:8001/admin-web
```

Ingresa:

- `API_ADMIN_KEY`
- nombre del token
- descripción opcional
- límites diarios y por minuto

## Ver PostgreSQL

### Desde terminal

```bash
docker exec -it sunat-postgres psql -U sunat -d sunat
```

Dentro de `psql`:

```sql
SELECT COUNT(*) FROM padron_ruc;
```

### pgAdmin

Abre:

```text
http://localhost:8080
```

Credenciales:

- Email: `admin@admin.com`
- Password: `admin123`

Para conectar a PostgreSQL desde pgAdmin:

- Host: `postgres`
- Puerto: `5432`
- DB: `sunat`
- User: `sunat`
- Password: la de tu `.env`

## Comandos útiles

Ver logs:

```bash
docker logs sunat-api --tail=100
```

Entrar a PostgreSQL:

```bash
docker exec -it sunat-postgres psql -U sunat -d sunat
```

Contar registros:

```sql
SELECT COUNT(*) FROM padron_ruc;
```

Probar docs:

```bash
curl http://localhost:8001/docs
```

Importar padrón:

```bash
docker compose exec api python scripts/importar_padron.py /app/data/padron.txt
```

## Endpoints principales

- `GET /ruc/{ruc}`
- `GET /buscar?nombre=texto`
- `GET /estado/{estado}`
- `GET /condicion/{condicion}`
- `GET /ubigeo/{ubigeo}`
- `GET /health`

## Endpoints administrativos

- `POST /admin/api-keys`
- `GET /admin/api-keys`
- `GET /admin/api-keys/search`
- `PATCH /admin/api-keys/{api_key_id}/activate`
- `PATCH /admin/api-keys/{api_key_id}/deactivate`
- `DELETE /admin/api-keys/{api_key_id}`
- `POST /admin/api-keys/{api_key_id}/regenerate`
- `GET /admin/api-keys/{api_key_id}/stats`
- `GET /admin/api-keys/{api_key_id}/logs`

## Notas

- Todos los endpoints de consulta requieren `X-API-Key`.
- Los endpoints administrativos requieren `X-Admin-Key`.
- La API corre en `8001`.
- El contenedor también expone la UI web y pgAdmin.
