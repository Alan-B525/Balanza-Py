# Servidor Modbus RTU – Documentación Técnica

## Índice

1. [Descripción General](#descripción-general)
2. [Arquitectura](#arquitectura)
3. [Configuración](#configuración)
4. [Ciclo de Vida](#ciclo-de-vida)
5. [Formato de Datos](#formato-de-datos)
6. [Herramientas de Test](#herramientas-de-test)
7. [Conexión RS-485 entre 2 PCs](#conexión-rs-485-entre-2-pcs)
8. [Preguntas Frecuentes](#preguntas-frecuentes)

---

## Descripción General

El sistema de pesaje actúa como **servidor (esclavo) Modbus RTU** que publica continuamente el peso neto total y los 5 angulos en holding registers. Un cliente externo (PLC, PC, HMI) puede leer estos valores en cualquier momento mediante el protocolo Modbus RTU estándar sobre un enlace serial RS-485.

```
┌──────────────────────┐         RS-485          ┌──────────────────┐
│   PC - Balanza-Py    │ ◄─────────────────────► │   PLC / Cliente  │
│                      │                          │                  │
│  Sensor → Procesar   │     Modbus RTU @ 3Mbaud  │  Lee registros   │
│  → Publicar en HR    │     Slave ID: 1          │  cada ciclo      │
│    registros 1000+   │     Registro: 1000-1011  │                  │
└──────────────────────┘                          └──────────────────┘
```

### Características

| Propiedad | Valor |
|---|---|
| Protocolo | Modbus RTU (serial) |
| Rol | Esclavo (servidor) |
| Librería | pymodbus 3.12+ |
| Función soportada | 0x03 (Read Holding Registers) |
| ID esclavo | 1 (configurable) |
| Baudrate | 3.000.000 bps (configurable) |
| Paridad | Ninguna (configurable) |
| Tasa de publicación | Igual a la tasa de adquisición del sensor |

---

## Arquitectura

### Componentes

```
main.py (hilo de adquisición)
  │
  ├── SistemaPesaje → lee sensor → DataProcessor → datos procesados
  │
  ├── ModbusDataServer (modules/modbus_server.py)
  │     ├── Thread dedicado con asyncio event loop
  │     ├── ModbusSerialServer (pymodbus)
  │     ├── Datastore con holding registers
  │     └── push_data() ← llamado desde el loop de adquisición
  │
  └── data_queue → GUI (estado del LED, logs, datos)
```

### Archivos involucrados

| Archivo | Rol |
|---|---|
| `modules/modbus_server.py` | Clase `ModbusDataServer` – gestiona el server pymodbus |
| `main.py` | Crea, inicia, detiene el server. Llama `push_data()` en cada muestra |
| `modules/gui.py` | Muestra LED "MB" con estado del server (verde/gris/rojo) |
| `settings.json` | Configuración del puerto serial, baudrate, slave ID |

### Flujo de datos (por cada muestra)

```
1. Sensor (real o mock) envía dato
2. main.py lo procesa con DataProcessor → obtiene peso neto total
3. main.py convierte 6 valores (float32) a 12 registros (IEEE754)
4. main.py llama modbus_server.push_data([regs...])
5. push_data() escribe directamente en los holding registers del datastore
6. El servidor responde automáticamente al cliente que lea esos registros
```

> **Importante**: `push_data()` **no envía datos al cliente**. Solo actualiza el datastore interno. El cliente decide cuándo y qué tan rápido leer mediante polling (función 0x03).

---

## Configuración

### settings.json

La sección `transmissao` controla el servidor Modbus:

```json
{
  "transmissao": {
    "porta": "COM10",           // Puerto serial del adaptador RS-485
    "velocidade": 3000000,      // Baudrate en bps
    "paridade": "Nenhuma",      // Paridad: "Nenhuma", "Par", "Impar"
    "id_escravo_pc": 1,         // Slave ID Modbus (1-247)
    "swap_words": false         // Intercambiar palabras del FLOAT32
  }
}
```

### Parámetros del servidor

| Parámetro | Default | Descripción |
|---|---|---|
| `serial_port` | COM10 | Puerto COM del adaptador RS-485 del PC servidor |
| `baudrate` | 3.000.000 | Velocidad en bps. **Debe coincidir en cliente y servidor** |
| `parity` | N | Paridad: N (ninguna), E (par), O (impar) |
| `stopbits` | 1 | Bits de parada |
| `bytesize` | 8 | Bits de datos |
| `timeout` | 0.05 | Timeout en segundos para operaciones serial |
| `holding_start` | 1000 | Dirección base de los holding registers |

### Mapa de registros

| Dirección | Tipo | Contenido |
|---|---|---|
| **1000-1001** | Holding Register (HR) | Peso bruto total – **float32** |
| **1002-1003** | Holding Register (HR) | Angulo 1 – **float32** |
| **1004-1005** | Holding Register (HR) | Angulo 2 – **float32** |
| **1006-1007** | Holding Register (HR) | Angulo 3 – **float32** |
| **1008-1009** | Holding Register (HR) | Angulo 4 – **float32** |
| **1010-1011** | Holding Register (HR) | Angulo 5 – **float32** |
| Coil 0 | Coil | Data available flag (1 = dato actualizado) |

### Decodificacion de datos en el cliente

```
import struct

def regs_to_float32(hi, lo, swap_words=False):
  if swap_words:
    hi, lo = lo, hi
  packed = bytes([(hi >> 8) & 0xFF, hi & 0xFF, (lo >> 8) & 0xFF, lo & 0xFF])
  return struct.unpack('>f', packed)[0]

peso_kg = regs_to_float32(HR[1000], HR[1001])
ang1 = regs_to_float32(HR[1002], HR[1003])
ang2 = regs_to_float32(HR[1004], HR[1005])
ang3 = regs_to_float32(HR[1006], HR[1007])
ang4 = regs_to_float32(HR[1008], HR[1009])
ang5 = regs_to_float32(HR[1010], HR[1011])
```

> Si `swap_words` esta habilitado en settings, invertir los words al decodificar.

---

## Ciclo de Vida

### Diagrama de estados

```
                      ┌──────────────┐
          app inicia  │              │
      ───────────────►│  DESCONECTADO │◄──────── usuario desconecta
                      │  LED: ⚪ gris │          ┌─────────────────┐
                      └──────┬───────┘          │                 │
                             │                  │  DESCONECTANDO  │
                    usuario  │                  │  stop() server  │
                    conecta  │                  │  LED: ⚪ gris    │
                             ▼                  └────────┬────────┘
                      ┌──────────────┐                   │
                      │              │◄──────────────────┘
                      │  CONECTADO   │
                      │  start()     │
                      │  LED: 🟢 verde│
                      └──────┬───────┘
                             │
                    error en │ push_data
                    o start  │ falla
                             ▼
                      ┌──────────────┐     auto-retry
                      │    ERROR     │────────────────┐
                      │  LED: 🔴 rojo │     (cada 2s)  │
                      └──────────────┘◄───────────────┘
```

### Eventos detallados

#### 1. Usuario clickea CONECTAR

```
main.py → SistemaPesaje.conectar()
        → _start_modbus_if_needed()
            → ModbusDataServer(serial_port, baudrate, ...)
            → server.start()  # thread dedicado
            → data_queue: MODBUS_STATUS='connected'
            → GUI: LED MB = 🟢 verde
```

#### 2. Usuario clickea DESCONECTAR

```
main.py → SistemaPesaje.desconectar()
        → modbus_server.stop()  # shutdown() asyncio, espera 3s max
        → modbus_server = None
        → data_queue: MODBUS_STATUS='idle'
        → GUI: LED MB = ⚪ gris
```

#### 3. Falla el start del servidor (ej: puerto ocupado)

```
main.py → _start_modbus_if_needed()
        → Exception capturada
        → modbus_server = None
        → data_queue: MODBUS_STATUS='error'
        → GUI: LED MB = 🔴 rojo
        → Auto-retry cada 2 segundos mientras esté conectado
```

#### 4. Falla push_data (ej: server se corrompió)

```
main.py → push_data() retorna False
        → modbus_server.stop()
        → modbus_server = None
        → data_queue: MODBUS_STATUS='error'
        → GUI: LED MB = 🔴 rojo
        → Auto-retry cada 2 segundos (reinicia el server)
```

#### 5. Auto-retry exitoso

```
main.py → loop principal detecta modbus_server == None
        → si sistema conectado y no pausado
        → _start_modbus_if_needed()
        → server reinicia
        → LED MB = 🟢 verde
```

### Tolerancia a fallos

| Evento | ¿La app crashea? | ¿Qué pasa con la adquisición? | LED |
|---|---|---|---|
| Puerto Modbus no existe | No ❌ | Continúa normal ✅ | 🔴 |
| Puerto ocupado por otro proceso | No ❌ | Continúa normal ✅ | 🔴 |
| Error interno del server | No ❌ | Continúa normal ✅ | 🔴 |
| Cable RS-485 desconectado | No ❌ | Continúa normal ✅ | 🟢* |
| `push_data()` falla | No ❌ | Continúa normal ✅ | 🔴 |

> \* Si el cable se desconecta, el server sigue "vivo" pero el cliente no recibe respuestas. El LED permanece verde porque el server no detecta la desconexión física.

---

## Herramientas de Test

### Cliente Python (`scripts/modbus_client.py`)

Para pruebas de funcionalidad y diagnóstico rápido desde la misma PC.

```bash
# Requiere: venv con pymodbus, matplotlib

# Modo live – lectura continua con gráfico
python scripts/modbus_client.py --port COM9 --baud 3000000 --mode live

# Modo bench – prueba de velocidad máxima
python scripts/modbus_client.py --port COM9 --baud 3000000 --mode bench --duration 10

# Modo sweep – comparar diferentes intervalos de polling
python scripts/modbus_client.py --port COM9 --baud 3000000 --mode sweep
```

**Limitación**: ~44-50 Hz en COM virtual (overhead de Python + com0com).

### Cliente C (`scripts/modbus_bench.exe`)

Para simular un PLC a máxima velocidad. Zero dependencias externas.

```bash
# Compilar (requiere gcc/MinGW):
$env:PATH = "C:\msys64\mingw64\bin;$env:PATH"
gcc -O2 -o scripts\modbus_bench.exe scripts\modbus_bench.c -lm

# Ejecutar:
.\scripts\modbus_bench.exe COM9 3000000 1 1000 10
#                          │    │       │ │    └─ duración (segundos)
#                          │    │       │ └────── registro inicial
#                          │    │       └──────── slave ID
#                          │    └──────────────── baudrate
#                          └───────────────────── puerto COM
```

**Portátil**: copiar solo el `.exe` a otra PC. No necesita instalación.

### Comparación de rendimiento (COM virtual)

| Métrica | Python | C |
|---|---|---|
| Throughput | ~44 reads/s | ~49 reads/s |
| RTT mínimo | 9.3 ms | 5.0 ms |
| RTT mediana | 18.8 ms | 17.1 ms |
| RTT P95 | 32.5 ms | 31.4 ms |

> El cuello de botella en COM virtual es el driver com0com (~15ms latencia), no el lenguaje.

---

## Conexión RS-485 entre 2 PCs

### Hardware necesario

- 2× adaptadores USB-RS485 (uno por PC)
- Cable de 2 hilos (A, B) + GND
- Resistor de terminación 120Ω en los extremos (recomendado para distancias >10m)

### Cableado

```
PC Servidor (Balanza-Py)          PC Cliente (bench)
┌──────────┐                      ┌──────────┐
│ USB-RS485│                      │ USB-RS485│
│    A ●───┼──── cable ──────────┼─── A ●   │
│    B ●───┼──── cable ──────────┼─── B ●   │
│  GND ●───┼──── cable ──────────┼── GND ●  │
└──────────┘                      └──────────┘
    120Ω entre A y B                 120Ω entre A y B
    (si distancia > 10m)             (si distancia > 10m)
```

### Configuración del servidor (PC con Balanza-Py)

En `settings.json`, sección `transmissao`:

```json
{
  "transmissao": {
    "porta": "COM10",        // Puerto del adaptador USB-RS485 del servidor
    "velocidade": 3000000,
    "paridade": "Nenhuma",
    "id_escravo_pc": 1
  }
}
```

> **Verificar**: abrir Administrador de dispositivos → Puertos (COM & LPT) → ver qué COM asignó Windows al adaptador.

### Ejecución

**PC Servidor** (donde corre Balanza-Py):

```bash
python main.py
# → Clickear CONECTAR
# → LED MB debe quedar 🟢 verde
```

**PC Cliente** (donde corre el benchmark):

```bash
modbus_bench.exe COM3 3000000 1 1000 60
#                │    │       │ │    └── 60 segundos de test
#                │    │       │ └────── registro 1000
#                │    │       └──────── slave ID = 1 (mismo que id_escravo_pc)
#                │    └──────────────── baudrate (DEBE COINCIDIR con el servidor)
#                └───────────────────── puerto COM del adaptador del cliente
```

### Rendimiento esperado (RS-485 real)

| Baudrate | RTT estimado | Throughput estimado |
|---|---|---|
| 9600 | ~12 ms | ~80 reads/s |
| 115200 | ~3-5 ms | ~200-300 reads/s |
| 3000000 | ~0.5-2 ms | **500-1000+ reads/s** |

---

## Preguntas Frecuentes

### ¿El servidor envía datos automáticamente al cliente?

**No.** Modbus RTU es un protocolo maestro-esclavo. El servidor (esclavo) solo **responde** cuando el cliente (maestro) envía una solicitud. El servidor actualiza sus registros internos a la tasa de adquisición del sensor, pero solo transmite el dato cuando el cliente lo pide.

### ¿Qué pasa si el cliente lee más lento que la tasa de publicación?

El servidor **siempre tiene el último dato disponible**. Si publicás a 300 Hz y el cliente lee a 50 Hz, cada lectura obtiene el valor más reciente. No se pierden datos — el cliente simplemente no ve todas las muestras intermedias.

### ¿Qué pasa si no hay cliente conectado?

Nada. El servidor funciona normalmente, actualizando registros en memoria. Cuando un cliente se conecte y envíe una solicitud, recibirá el valor actual. No hay acumulación de datos ni overflow.

### ¿Puedo conectar varios clientes al mismo bus RS-485?

**No simultáneamente.** En RS-485 half-duplex, solo un maestro puede hablar a la vez. Si necesitás múltiples lectores, un solo maestro debe coordinar el acceso al bus.

Sin embargo, el servidor soporta múltiples clientes **secuenciales** (uno desconecta, otro conecta).

### ¿El baudrate afecta la precisión de los datos?

No. El baudrate solo afecta la **velocidad de transferencia**, no la precisión. Los datos se transmiten como enteros de 32 bits con resolución de 1 gramo (escala ×1000). Un valor de 618442 siempre significa 618.442 kg, independiente del baudrate.

### ¿Qué pasa si el cable RS-485 se corta durante la operación?

- **La aplicación no crashea** — la adquisición del sensor continúa normalmente.
- **El LED MB permanece verde** — el servidor no detecta desconexión física del bus.
- **El cliente recibirá timeouts** — sus solicitudes no llegarán al servidor.
- **Al reconectar el cable**, la comunicación se reanuda automáticamente.

### ¿Puedo cambiar el registro de lectura?

Sí. El servidor publica en el registro `holding_start` (default: 1000). Se puede modificar en el código de `modules/modbus_server.py` cambiando el parámetro:

```python
ModbusDataServer(..., holding_start=2000)
```

### ¿Cómo se codifica el peso en los registros?

Los datos de peso bruto y los 5 ángulos se transmiten en formato de punto flotante de precisión simple (float32 de 32 bits según la norma IEEE 754), ocupando dos registros de 16 bits cada uno.

Ejemplo de decodificación en Python:
```python
import struct

def regs_to_float32(hi, lo, swap_words=False):
    if swap_words:
        hi, lo = lo, hi
    packed = bytes([(hi >> 8) & 0xFF, hi & 0xFF, (lo >> 8) & 0xFF, lo & 0xFF])
    return struct.unpack('>f', packed)[0]

# El peso bruto total está en los registros 1000 y 1001
peso_bruto = regs_to_float32(reg[1000], reg[1001])
```

### ¿Los 3 Mbaud son necesarios?

No. 3 Mbaud permite latencia mínima, pero solo si tanto el adaptador USB-RS485 como el PLC lo soportan. Si tu hardware no soporta 3 Mbaud, podés bajar a cualquier baudrate estándar (9600, 19200, 38400, 57600, 115200, etc.). Solo asegurate de que **coincida en ambos extremos**.

### ¿Cómo verifico que el servidor está funcionando?

1. **LED MB en la GUI**: 🟢 verde = funcionando, 🔴 rojo = error, ⚪ gris = detenido
2. **Log en la GUI**: muestra "Modbus RTU iniciado em COMx" al arrancar
3. **Cliente de test**: correr `modbus_bench.exe` o `modbus_client.py` y verificar que lee valores

### ¿Puedo usar el servidor por TCP/IP en lugar de serial?

No actualmente. El servidor está configurado para **Modbus RTU serial** exclusivamente. Para TCP, habría que crear una instancia de `ModbusTcpServer` en lugar de `ModbusSerialServer`. Esto requeriría cambios en `modbus_server.py`.

### ¿Qué versión de pymodbus necesito?

**pymodbus 3.12 o superior**. Versiones anteriores usan una API diferente (`StartSerialServer`, clases de framer distintas) que no es compatible con este código.

Verificar: `pip show pymodbus | grep Version`
