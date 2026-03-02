# Importa Acreditados SIS - Python

Este proyecto es una aplicación Python diseñada para gestionar la importación de acreditados del SIS (Seguro Integral de Salud). Incluye un entorno de despliegue contenerizado con Docker que simula la infraestructura de base de datos necesaria.

## Estructura del Proyecto (Profesional)

*   `src/`: Código fuente de la aplicación Flask.
*   `Dockerfile`: Definición de la imagen optimizada (Multi-stage).
*   `docker-compose.yml`: Orquestación para el despliegue de la aplicación.

## Requisitos Previos

*   [Docker Desktop](https://www.docker.com/products/docker-desktop) instalado y corriendo.
*   Git (opcional).

### Paso 1: Iniciar la aplicación

Desde la raíz del proyecto, ejecuta:

```bash
docker-compose up --build
```

**Qué sucede:**
1.  Se construye la imagen de la aplicación Python optimizada.
### Paso 2: Ejecución e Importación
1. Accede a la aplicación en `http://localhost:51423`.
2. Ingresa los datos de tu servidor **MSSQL 2012** (IP, Puerto, Usuario, Password).
3. Sube el archivo `.zip` con los acreditados.
4. La aplicación creará una tabla temporal `#` en el servidor destino, realizará la carga y luego el merge final.

## Solución de Problemas

*   **Error de inicio de sesión (18456)**:
    *   Verifica que el usuario SQL tenga permisos de creación de tablas temporales y escritura en la tabla final.
*   **Protocolo de Seguridad (SSL/TLS)**:
    *   La imagen está preconfigurada para soportar TLSv1.0 y niveles de seguridad reducidos compatibles con SQL 2012.
*   **Conexión Rechazada**:
    *   Confirma que el servidor SQL permita conexiones remotas y que el puerto esté abierto en el firewall.
