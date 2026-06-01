Sistema Bancario Distribuido con Tolerancia a Fallos
Proyecto universitario de Sistemas Distribuidos que implementa una red de tres bancos (Perú, Chile, Colombia) con comunicación gRPC, transacciones distribuidas atómicas (2PC), elección de líder (Algoritmo Bully) y monitoreo en tiempo real con Prometheus y Grafana.

Tabla de Contenidos
Descripción General

Arquitectura del Sistema

Tecnologías Utilizadas

Requisitos Previos

Instalación y Ejecución

Estructura del Proyecto

Consideraciones de Diseño

Autores

Descripción General
El sistema simula un entorno bancario distribuido donde tres bancos independientes (Perú, Chile, Colombia) gestionan cuentas de clientes y permiten realizar operaciones financieras de forma transparente. Los usuarios pueden consultar saldos, depositar, retirar, transferir entre cuentas del mismo banco (local) o entre bancos diferentes (interbancaria con 2PC).

Características Principales
Transacciones Distribuidas Atómicas (2PC): Garantiza que las transferencias interbancarias se completen completamente o se aborten sin afectar la consistencia.

Tolerancia a Fallos con Algoritmo Bully: Detección automática de caídas de nodos y elección de un nuevo coordinador.

Monitoreo en Tiempo Real: Métricas expuestas a Prometheus y visualizadas en dashboards de Grafana.

Frontend Fintech Profesional: Interfaz moderna con diseño responsivo, modo claro/oscuro, y componentes interactivos para la gestión bancaria.

Comunicación gRPC: Protocolo de alto rendimiento para la comunicación entre servicios.

Arquitectura del Sistema
El sistema sigue una arquitectura de microservicios con tres nodos principales (bancos) y un frontend unificado. La comunicación entre componentes se realiza mediante gRPC, y la coordinación distribuida se maneja con los algoritmos Bully (elección de líder) y Two-Phase Commit (transacciones atómicas).

Diagrama de Componentes
text
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Flask)                         │
│  - Dashboard, Cuentas, Transferencias, Historial, Monitoreo    │
│  - API Gateway para gRPC                                       │
└────────────┬─────────────────────┬─────────────────┬────────────┘
             │                     │                 │
      ┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────┐
      │  Banco Perú │      │ Banco Chile │      │Banco Colombia│
      │  :50051     │      │  :50052     │      │  :50053     │
      │  Métricas   │      │  Métricas   │      │  Métricas   │
      │  :8000      │      │  :8001      │      │  :8002      │
      └──────┬──────┘      └──────┬──────┘      └──────┬──────┘
             │                    │                    │
             └────────────────────┼────────────────────┘
                                 │
                        ┌────────▼────────┐
                        │   Prometheus    │
                        │    :9090        │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │    Grafana      │
                        │    :3000        │
                        └─────────────────┘
Componentes Clave
Servidores gRPC (Bancos):

Implementan la lógica de negocio (cuentas, transacciones).

Almacenan datos en archivos JSON locales.

Ejecutan los protocolos Bully y 2PC.

Exponen métricas a Prometheus.

Frontend Flask:

Sirve las vistas HTML/CSS/JS con Jinja2.

Actúa como API Gateway para las llamadas gRPC desde el navegador.

Coordina las transferencias interbancarias como coordinador 2PC.

Prometheus + Grafana:

Recolectan y visualizan métricas de salud, rendimiento y estado de los nodos.

Tecnologías Utilizadas
Capa	Tecnología
Backend	Python 3.10+, gRPC, Protobuf
Frontend	Flask, Jinja2, Tailwind CSS, JavaScript
Persistencia	Archivos JSON
Monitoreo	Prometheus, Grafana
Comunicación	gRPC (Protocol Buffers)
Coordinación	Algoritmo Bully, Two-Phase Commit
Contenedores	Docker, Docker Compose (opcional)
Requisitos Previos
Python 3.10 o superior

Pip (gestor de paquetes de Python)

Prometheus (descargable desde prometheus.io)

Grafana (opcional, descargable desde grafana.com)

Instalación y Ejecución
1. Clonar el repositorio
bash
git clone <URL_DEL_REPOSITORIO>
cd Proyecto_Final_SD
2. Crear y activar entorno virtual
bash
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate
3. Instalar dependencias
bash
pip install -r requirements.txt
4. Generar los stubs gRPC
Ejecuta este comando en cada una de las carpetas bank-peru, bank-chile, bank-colombia y flask-frontend:

bash
python -m grpc_tools.protoc -I../proto --python_out=. --grpc_python_out=. ../proto/bank.proto
5. Iniciar los servidores bancarios
Abre tres terminales separadas y ejecuta:

bash
# Terminal 1 - Banco Perú
cd bank-peru
python server.py

# Terminal 2 - Banco Chile
cd bank-chile
python server.py

# Terminal 3 - Banco Colombia
cd bank-colombia
python server.py
6. Iniciar Prometheus
Asegúrate de tener el archivo prometheus.yml en la misma carpeta que el ejecutable de Prometheus. Luego ejecuta:

bash
./prometheus --config.file=prometheus.yml
7. Iniciar el frontend Flask
bash
cd flask-frontend
python app.py
8. Acceder a la aplicación
Frontend: http://localhost:5000

Prometheus: http://localhost:9090

Grafana: http://localhost:3000 (si está instalado)

Credenciales de prueba: admin / admin

Estructura del Proyecto
text
.
├── bank-peru/                  # Servidor gRPC del Banco Perú
│   ├── server.py               # Lógica del banco, Bully, 2PC
│   ├── data/                   # Cuentas y transacciones (JSON)
│   └── requirements.txt
├── bank-chile/                 # Ídem para Chile
├── bank-colombia/              # Ídem para Colombia
├── flask-frontend/             # Frontend y API Gateway
│   ├── app.py                  # Rutas Flask y lógica de la UI
│   ├── templates/              # Plantillas Jinja2
│   ├── static/                 # CSS, JS, imágenes
│   ├── bank_client.py          # Cliente gRPC para los bancos
│   ├── bully.py                # Consulta del estado del clúster
│   └── two_phase_commit.py     # Coordinador 2PC
├── proto/
│   └── bank.proto              # Definición de servicios gRPC
├── prometheus.yml              # Configuración de Prometheus
├── requirements.txt            # Dependencias globales
└── README.md
Consideraciones de Diseño
1. Transparencia de Acceso
El usuario interactúa con un único frontend que oculta la complejidad de la red subyacente. Las cuentas de diferentes bancos se muestran en una sola tabla, y las transferencias interbancarias se ejecutan sin que el usuario tenga que preocuparse por la ubicación de los fondos.

2. Consistencia y Atomicidad
Las transferencias interbancarias utilizan el protocolo Two-Phase Commit (2PC) para garantizar que los débitos y créditos se realicen de forma atómica. Si cualquier participante falla durante la transacción, se ejecuta un rollback completo, manteniendo la integridad de los saldos.

3. Tolerancia a Fallos
El Algoritmo Bully permite que los nodos detecten la caída del coordinador actual y elijan uno nuevo automáticamente. Esto se complementa con un sistema de heartbeats periódicos que monitorean la salud de los nodos.

4. Control de Concurrencia
Cada banco implementa bloqueos a nivel de cuenta para evitar condiciones de carrera durante operaciones simultáneas. Los bloqueos se adquieren en orden consistente para prevenir deadlocks.

5. Escalabilidad
La arquitectura basada en gRPC permite agregar nuevos bancos simplemente desplegando una nueva instancia del servidor y registrándola en el frontend. La lógica de coordinación (Bully, 2PC) escala horizontalmente sin cambios significativos.

6. Monitoreo y Observabilidad
Las métricas expuestas a Prometheus permiten supervisar en tiempo real:

Tasa de transacciones por banco

Latencia de las fases del 2PC

Estado de los nodos (líder, seguidor, caído)

Salud general del clúster

7. Persistencia Ligera
Se optó por archivos JSON en lugar de bases de datos tradicionales para simplificar el despliegue y la depuración. Cada banco mantiene sus propios datos, simulando un sistema de archivos distribuido real pero sin la complejidad de replicación automática (que se puede añadir como trabajo futuro).

8. Decisiones de Diseño del Frontend
Tailwind CSS con un sistema de diseño personalizado (variables CSS para modo claro/oscuro).

Canvas API para la visualización de la topología de red en tiempo real.

Polling periódico para actualizar el timeline de eventos y el estado de los nodos sin necesidad de WebSockets.

Notificaciones Toast reutilizables para feedback de acciones del usuario.

Proyecto Final de Sistemas Distribuidos - Universidad Nacional de San Agustín, 2026.