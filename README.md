# Mes-Autoparty: Indicaciones e Instrucciones del Proyecto

Este documento define el enfoque, las reglas y los pasos a seguir para el desarrollo de nuestro proyecto "MES-lite".

## 1. Alcance "MVP" (Producto Mínimo Viable)
El objetivo es lograr un primer entregable que aporte valor inmediato y sea instalable en "cualquier máquina". El MVP incluye:

*   **Conexión OPC UA** con el PLC Siemens.
*   **Modelo de máquina estándar**: estados, modos, fallos y producción.
*   **Gestión de parámetros**: lectura y escritura con trazabilidad (quién, cuándo, desde qué receta).
*   **Captura de eventos**: cambios de estado, fallos y motivos de parada.
*   **Cálculo OEE básico**: (Disponibilidad / Performance / Calidad) y un dashboard simple.
*   **Persistencia local (Edge)** + posibilidad de exportación o replicación opcional.

Esto constituye un sistema "MES-lite" pero altamente útil.

## 2. El Núcleo: El "Contrato de Datos" PLC ↔ MES
Esta es la parte más importante. Antes de programar, se debe definir qué expone el PLC por OPC UA y bajo qué reglas. Lo ideal es utilizar un UDT/DB estándar (en Siemens) que sea idéntico para todas las máquinas.

### Modelo mínimo de tags (Orientativo)

**a) Identidad / Heartbeat**
*   `MachineId`, `LineId`, `CellId`
*   `PLC_Heartbeat` (toggle/contador), `MES_Heartbeat`
*   Versionado del contrato (`SchemaVersion`)

**b) Estado y Modo**
*   `OperationMode` (AUTO / MANUAL / ...)
*   `MachineState` (RUN, STOP, IDLE, FAULT, STARVED, BLOCKED, SETUP…)
*   `StateTimestamp` / contador de cambios
*   `CurrentOrderId` / `BatchId` (si aplica)

**c) Producción y Calidad**
*   `GoodCount`, `RejectCount`, `TotalCount`
*   `IdealCycleTime` (o Rate)
*   `CurrentCycleTime` (si aplica)

**d) Fallos / Paradas**
*   `ActiveFaultId`, `ActiveFaultText` (o código)
*   `StopReasonId` (cuando está parada)
*   Lista/bitfield de fallos activos

**e) Parámetros**
*   `ParameterSet`: `{Id, Version, ApplyCmd, ApplyAck, ApplyResult}`
*   Array de parámetros: `{ParamId, Value, Min, Max, Unit, RW, LastChanged...}`

**f) Eventos**
Un buffer FIFO en el PLC o, más simple, un `EventCounter` + `LastEvent`.
*   `EventId`, `EventType`, `Code`, `Timestamp`, `Value`

> **Regla de oro:** Sin tiempos (timestamps) coherentes o contadores monotónicos, será imposible reconstruir correctamente la historia posterior.

## 3. Patrón de Integración OPC UA
Existen 3 patrones típicos de integración para decidir cómo fluye la información:

1.  **Polling de tags (Simple y robusto):** El edge lee cada X ms/seg.
2.  **Subscription OPC UA (Mejor):** El edge se suscribe a cambios (DataChange).
3.  **Eventos (Buffer) + lectura:** El PLC guarda eventos en un FIFO y el edge los "drena".

**Recomendación para empezar (Combinación):**
*   **Subscription** para estados y contadores (cambios).
*   **Polling lento** (5–10s) para *sanity check* y control de reconexiones.
*   *Posteriormente, si se requiere alta fiabilidad, se puede añadir el FIFO de eventos.*

## 4. Arquitectura en el Edge
Para asegurar que el sistema sea instalable en cualquier máquina, la arquitectura (típica en la industria) será la siguiente:

*   **Collector / Connector (OPC UA Client):** Se conecta al PLC, normaliza los tags, y gestiona tanto la calidad de los datos como las reconexiones.
*   **Normalizer / Domain Layer:** Traduce los tags crudos al "modelo MES" (estado, evento, parámetro, etc.).
*   **Storage (Local):** Uso de SQLite o PostgreSQL (dependiendo del volumen de datos).
*   **Services:**
    *   Servicio OEE.
    *   Servicio de Parámetros (para aplicar y cerrar el lazo).
    *   Servicio de Eventos.
*   **API + UI:** Interfaz basada en REST/GraphQL junto a un dashboard web.
*   **Cloud Sync (Opcional):** Uso de MQTT, Kafka o HTTP si más adelante se decide centralizar la información.

*Esto permite dividir el trabajo: un rol se puede encargar de los datos/ETL/Storage (Data Engineer) y otro del modelo industrial y el contrato del PLC.*

## 5. Implementación Inicial en Siemens (DB + Interface)
El arranque a nivel físico/PLC de Siemens consistirá en:

1.  **Crear un DB `MES_Interface`** con UDTs estables.
2.  **Implementar en el PLC:**
    *   **StateManager:** (Ej. estilo GEMMA) para exponer el `MachineState`.
    *   **Counters** + `IdealCycleTime`.
    *   **Fault mapping:** Para exponer el `ActiveFaultId` / `FaultBits`.
    *   **Handshake de parámetros:** Proceso de apply (comando, confirmación y resultado).
3.  **Publicar el DB:** Hacer el DB accesible vía OPC UA (soportado por S7-1500).

> **Asegurar desde el principio:** Naming conventions (espacio de nombres estable) y versionado del contrato (`SchemaVersion`).

## 6. Handshake para Escritura de Parámetros
Para evitar problemas, **nunca realizar un "write directo y ya"**. El patrón recomendado es el siguiente:

**1. El MES escribe:**
*   `ParamSetId`, `ParamValues`...
*   `ApplyCmd` (incrementa un token)

**2. El PLC responde:**
*   `ApplyAck` (copia el token recibido)
*   `ApplyResult` (OK / Código de Error)
*   `AppliedTimestamp`

*Este enfoque garantiza trazabilidad, permite reintentos seguros y elimina la dependencia de la temporización (timing).*

## 7. Plan de Primera Iteración (Orden Recomendado)

Sigue este orden de desarrollo para avanzar de forma segura:

1.  **Especificación del contrato:** Crear un documento exhaustivo con tags, tipos, reglas y estados.
2.  **Prototipo Siemens:** Generar el DB con estado, contadores, fallos y el handshake.
3.  **Prototipo Edge:** Configurar el cliente OPC UA, la ingesta y el almacenamiento.
4.  **OEE v1:** Implementar disponibilidad, rendimiento (performance) y calidad mediante reglas simples.
5.  **UI Simple:** Visualizar el estado actual, el timeline de paradas y el OEE del turno/día.
6.  **Endurecimiento del sistema:** Asegurar reconexiones, calidad del dato, control de la hora (reloj), buffering y backups.

---
*Proyecto creado para conectar un PLC con una base de datos de manera robusta y escalable.*
