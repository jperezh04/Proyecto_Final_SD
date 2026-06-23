# Sistema Bancario Distribuido con Tolerancia a Fallos

Proyecto desarrollado para el curso de Sistemas Distribuidos de la Universidad Nacional de San Agustín. El sistema implementa una red de tres bancos distribuidos (Perú, Chile y Colombia) que se comunican mediante gRPC, incorporando mecanismos de coordinación y tolerancia a fallos mediante el protocolo Two-Phase Commit (2PC) y el Algoritmo Bully para elección de líder.

## Tabla de Contenidos

* Descripción General
* Arquitectura del Sistema
* Tecnologías Utilizadas
* Requisitos Previos
* Instalación y Ejecución
* Estructura del Proyecto
* Consideraciones de Diseño
* Trabajo Futuro
* Autores

---

# Descripción General

El sistema simula una plataforma bancaria distribuida conformada por tres entidades financieras independientes. Cada banco administra sus propias cuentas y transacciones, manteniendo autonomía operativa mientras participa en operaciones distribuidas cuando se requieren transferencias entre bancos.

Los usuarios interactúan mediante una interfaz web unificada que permite consultar cuentas, visualizar movimientos y realizar operaciones financieras sin necesidad de conocer la ubicación física o lógica de los datos.

## Funcionalidades Principales

### Comunicación Distribuida mediante gRPC

Los bancos se comunican utilizando gRPC y Protocol Buffers, permitiendo intercambiar información de forma eficiente entre los distintos nodos del sistema.

### Transferencias Interbancarias con Two-Phase Commit (2PC)

Las transferencias entre bancos utilizan el protocolo Two-Phase Commit para coordinar las operaciones de débito y crédito entre participantes, garantizando que la transacción se complete de forma consistente o sea cancelada.

### Elección de Líder mediante Algoritmo Bully

Los nodos monitorean la disponibilidad del coordinador mediante heartbeats periódicos. Ante la detección de una falla, se inicia un proceso de elección basado en el Algoritmo Bully para seleccionar un nuevo líder.

### Monitoreo del Sistema

Cada banco expone métricas operativas que pueden ser recolectadas por Prometheus y visualizadas mediante dashboards en Grafana para supervisar el estado general del sistema.

### Interfaz Web Unificada

El frontend desarrollado con Flask proporciona acceso centralizado a las operaciones bancarias y a la información del clúster distribuido.

---

# Arquitectura del Sistema

El sistema sigue una arquitectura distribuida basada en servicios independientes que colaboran mediante llamadas remotas gRPC.

```text
┌────────────────────────────────────────────────────────────┐
│                    Frontend Flask                          │
│  Dashboard · Cuentas · Transferencias · Monitoreo         │
└───────────────┬────────────────────────────────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
┌───▼───┐   ┌───▼───┐   ┌───▼────┐
│ Perú  │   │ Chile │   │Colombia│
│ :50051│   │:50052 │   │ :50053 │
└───┬───┘   └───┬───┘   └───┬────┘
    │           │           │
    └───────────┼───────────┘
                │
        ┌───────▼───────┐
        │  Prometheus   │
        │     :9090     │
        └───────┬───────┘
                │
        ┌───────▼───────┐
        │    Grafana    │
        │     :3000     │
        └───────────────┘
```

## Componentes Principales

### Bancos Distribuidos

Cada banco:

* Mantiene sus propias cuentas y transacciones.
* Expone servicios gRPC.
* Participa en elecciones de líder.
* Participa en transacciones distribuidas.
* Publica métricas para monitoreo.

### Frontend Flask

Responsable de:

* Gestionar la interacción con los usuarios.
* Actuar como cliente de los servicios gRPC.
* Centralizar el acceso a la información de los bancos.
* Mostrar información de monitoreo y estado del sistema.

### Sistema de Monitoreo

Prometheus recopila métricas expuestas por los bancos y Grafana permite visualizar indicadores relevantes sobre el comportamiento del sistema.

---

# Tecnologías Utilizadas

| Capa                     | Tecnologías                             |
| ------------------------ | --------------------------------------- |
| Backend                  | Python, gRPC, Protocol Buffers          |
| Frontend                 | Flask, Jinja2, Tailwind CSS, JavaScript |
| Persistencia             | Archivos JSON                           |
| Monitoreo                | Prometheus, Grafana                     |
| Comunicación             | gRPC                                    |
| Coordinación Distribuida | Two-Phase Commit, Algoritmo Bully       |

---

# Requisitos Previos

* Python 3.10 o superior
* pip
* Prometheus
* Grafana (opcional)

---

# Instalación y Ejecución

## 1. Clonar el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd Proyecto_Final_SD
```

## 2. Crear entorno virtual

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Linux/Mac:

```bash
source venv/bin/activate
```

## 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

## 4. Generar archivos gRPC

Ejecutar en cada componente que utilice el archivo proto:

```bash
python -m grpc_tools.protoc -I../proto --python_out=. --grpc_python_out=. ../proto/bank.proto
```

## 5. Iniciar los bancos

Banco Perú:

```bash
python server.py
```

Banco Chile:

```bash
python server.py
```

Banco Colombia:

```bash
python server.py
```

## 6. Iniciar Prometheus

```bash
prometheus --config.file=prometheus.yml
```

## 7. Iniciar el frontend

```bash
python app.py
```

---

# Estructura del Proyecto

```text
Proyecto_Final_SD
├── bank-peru/
├── bank-chile/
├── bank-colombia/
├── flask-frontend/
├── proto/
├── prometheus.yml
├── requirements.txt
└── README.md
```

---

# Consideraciones de Diseño

## Transparencia de Acceso

Los usuarios interactúan mediante una única interfaz, independientemente del banco donde se encuentren las cuentas.

## Consistencia

Las transferencias interbancarias se coordinan mediante 2PC para mantener la integridad de los datos entre participantes.

## Tolerancia a Fallos

El Algoritmo Bully permite seleccionar un nuevo coordinador cuando el líder deja de responder.

## Control de Concurrencia

Las operaciones sobre cuentas utilizan mecanismos de bloqueo para evitar conflictos durante accesos simultáneos.

## Observabilidad

Las métricas operativas permiten monitorear el estado de los nodos y la actividad general del sistema.

## Persistencia

Cada banco mantiene su información localmente mediante archivos JSON, simplificando el despliegue y la comprensión del sistema.

---

# Trabajo Futuro

Como posibles extensiones del proyecto se consideran:

* Replicación de datos entre bancos.
* Persistencia mediante bases de datos relacionales.
* Recuperación automática de transacciones tras fallos.
* Balanceo de carga.
* Despliegue completo mediante Docker Compose.
* Incorporación de mecanismos de autenticación y autorización más robustos.

---

# Autores

Proyecto desarrollado para el curso de Sistemas Distribuidos.

Universidad Nacional de San Agustín – 2026.


---

## Ejecución rápida con Docker

También se puede levantar todo el sistema con Docker Compose:

```bash
docker compose up --build
```

Servicios principales:

- Frontend Flask: `http://localhost:5000`
- Prometheus: `http://localhost:9090`
- Banco Perú gRPC: `localhost:50051`
- Banco Chile gRPC: `localhost:50052`
- Banco Colombia gRPC: `localhost:50053`

Login de prueba:

```txt
Usuario: admin
Contraseña: admin
```

Para más detalle revisar `README_DOCKER.md`.
