# Análisis del proyecto y correcciones realizadas

## Estado general

El proyecto sí tiene una base funcional: un frontend Flask, tres bancos independientes por gRPC, comunicación entre nodos, Two-Phase Commit para transferencias interbancarias, algoritmo Bully para coordinación y métricas para Prometheus.

La parte crítica que sí funciona es:

- Los tres bancos levantan como servicios gRPC: Perú, Chile y Colombia.
- El frontend puede conectarse a los tres nodos.
- Las cuentas se leen desde los archivos JSON de cada banco.
- Las transferencias locales modifican saldos.
- Las transferencias interbancarias ejecutan PREPARE y COMMIT mediante 2PC.
- El módulo de coordinación detecta líder y permite pausar/reanudar nodos.

## Problemas encontrados

### 1. Error de dependencias gRPC

Los archivos `bank_pb2_grpc.py` habían sido generados con una versión de gRPC más nueva que la indicada en `requirements.txt`. Por eso el proyecto podía fallar al iniciar con este error:

```txt
RuntimeError: The grpc package installed is at version 1.80.0, but the generated code depends on grpcio>=1.81.1
```

Corrección aplicada:

- Se actualizó `requirements.txt` a `grpcio>=1.81.1` y `grpcio-tools>=1.81.1`.
- Se regeneraron los archivos gRPC desde `proto/bank.proto`.

### 2. `/monitoring` podía romper con error 500

La pantalla de monitoreo fallaba cuando Prometheus respondía, pero no devolvía métricas completas por nodo. El problema era una variable `cpu_proxy` usada antes de existir.

Corrección aplicada:

- Se inicializó `cpu_proxy = 0` antes del recorrido de métricas.
- La pantalla `/monitoring` ya no cae por ese caso.

### 3. Transferencias con monto 0 o negativo

El backend aceptaba transferencias con monto `0` o negativo. Eso era grave porque un monto negativo podía alterar los saldos al revés.

Corrección aplicada:

- Se validó `amount > 0` en:
  - API Flask `/api/transfer`
  - `Deposit`
  - `Withdraw`
  - `TransferLocal`
  - `Prepare` del 2PC
- También se bloqueó transferir a la misma cuenta.

### 4. Nodo pausado seguía permitiendo operaciones bancarias

El nodo podía estar pausado en coordinación, pero todavía podía responder operaciones como balance o transferencia.

Corrección aplicada:

- Si un nodo está pausado, ahora rechaza operaciones financieras con estado `UNAVAILABLE`.

### 5. Datos dummy en varias pantallas

Había datos quemados en:

- `/history`: movimientos ficticios tipo JPMorgan.
- `/banks`: cantidades ficticias como 14,205 cuentas o volúmenes inventados.
- `/transfers`: lista fija de solo algunas cuentas.
- `/dashboard`: líder, hora de sincronización y conteos parcialmente quemados.
- `bank_client.py`: asumía que siempre existían `PE001`, `PE002`, `PE003`, etc.

Corrección aplicada:

- Se agregó `ListAccounts` al proto para que el frontend consulte cuentas reales desde los bancos.
- Se agregó `GetTransactions` para consultar movimientos reales registrados por los nodos.
- `/transfers` ahora muestra cuentas reales obtenidas desde gRPC.
- `/banks` ahora calcula cuentas y volumen desde las cuentas reales.
- `/history` ahora se alimenta de movimientos reales, no de datos ficticios.
- `/dashboard` toma cuentas, bancos conectados, líder y movimientos desde servicios reales.

## Datos dummy que aún existen o se deben reemplazar después

Todavía hay una parte que sigue siendo de demostración:

- Login fijo: `admin / admin`.
- Las cuentas iniciales siguen siendo archivos JSON semilla dentro de cada banco.
- No hay una base de datos real todavía.
- No existe un módulo real de clientes/usuarios para asociar cuentas a usuarios.
- Prometheus/Grafana todavía dependen de ejecución local.

## Qué se debe hacer para pasar a datos reales

Para cambiar de datos dummy a datos reales, lo correcto sería:

1. Reemplazar los JSON de cuentas por una base de datos real o por archivos importados desde CSV/API.
2. Crear una tabla o colección de usuarios/clientes.
3. Relacionar cada cuenta con un cliente real mediante `owner` o `customer_id`.
4. Cambiar el login `admin/admin` por autenticación real.
5. Hacer que `ListAccounts(owner)` filtre por el usuario autenticado.
6. Guardar todos los movimientos en una tabla/transacción persistente, no solo en JSON.
7. Preparar volúmenes Docker con persistencia para que los saldos no se pierdan al reiniciar.

## Mejoras frontend aplicadas

En la pantalla de transferencias:

- Se agregaron notificaciones tipo toast en lugar de solo `alert`.
- Se muestra mensaje de éxito cuando el movimiento se completa.
- Se muestra error claro cuando el backend rechaza la operación.
- Se bloquea el botón mientras la transferencia se procesa.
- Las cuentas origen ahora se filtran según el banco seleccionado.
- Se evita enviar cuentas cruzadas incorrectas desde el frontend.

## Docker

No se agregó Docker todavía, porque se acordó hacerlo al final. El proyecto ya quedó más ordenado para dockerizar después, principalmente porque:

- Las direcciones de bancos pueden venir desde variables de entorno.
- El frontend ya no depende de cuentas quemadas.
- El proto centraliza mejor cuentas y movimientos.
- La persistencia JSON está separada por banco y luego puede montarse como volumen.

