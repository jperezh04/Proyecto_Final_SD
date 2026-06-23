# Ejecución con Docker

Esta versión agrega Docker y Docker Compose para levantar todo el sistema distribuido con un solo comando.

## Servicios incluidos

- `bank-peru`: nodo gRPC de Perú, puerto `50051`, métricas `8000`.
- `bank-chile`: nodo gRPC de Chile, puerto `50052`, métricas `8001`.
- `bank-colombia`: nodo gRPC de Colombia, puerto `50053`, métricas `8002`.
- `prometheus`: recolector de métricas, puerto `9090`.
- `flask-frontend`: interfaz web, puerto `5000`.

## Cómo levantar el proyecto

Desde la raíz del proyecto:

```powershell
docker compose up --build
```

Luego entra en el navegador a:

```txt
http://localhost:5000
```

Login de prueba:

```txt
Usuario: admin
Contraseña: admin
```

Prometheus queda disponible en:

```txt
http://localhost:9090
```

## Comandos útiles

Levantar en segundo plano:

```powershell
docker compose up --build -d
```

Ver logs:

```powershell
docker compose logs -f
```

Ver logs de un servicio específico:

```powershell
docker compose logs -f flask-frontend
docker compose logs -f bank-peru
```

Detener todo:

```powershell
docker compose down
```

Detener y borrar datos de Prometheus:

```powershell
docker compose down -v
```

## Nota sobre los archivos JSON

Las carpetas `data` de cada banco se montan como volúmenes vinculados al proyecto local:

```txt
./bank-peru/data
./bank-chile/data
./bank-colombia/data
```

Eso significa que las cuentas y transacciones guardadas por los contenedores quedan persistidas en archivos del proyecto.

## Qué se modificó para Docker

- El frontend ahora escucha en `0.0.0.0`, no solo en `localhost`.
- Las direcciones gRPC se leen desde variables de entorno.
- Los peers del algoritmo Bully también usan nombres de servicios Docker.
- Prometheus apunta a `bank-peru`, `bank-chile` y `bank-colombia` dentro de la red Docker.
