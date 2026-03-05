# Documentación de Implementación GitOps - Importa Acreditados SIS

Este documento detalla secuencialmente todos los pasos, configuraciones y resoluciones de problemas implementados para establecer el flujo de Integración y Despliegue Continuo (CI/CD) usando GitHub Actions y ArgoCD sobre un clúster K3s.

---

## 1. Conexión de ArgoCD con el Repositorio Privado (GitHub vía SSH)

**Objetivo:** Permitir que ArgoCD, desplegado en el clúster K3s, pueda leer los manifiestos de Kubernetes directamente desde el repositorio privado de GitHub.

**Problema encontrado:** Al intentar vincular el repositorio usando el CLI de `argocd` (`argocd repo add...`), el Ingress (Traefik) bloqueaba las peticiones gRPC retornando un error `404 (Not Found)`.

**Solución Implementada:**
Se optó por el método declarativo y exacto de Kubernetes: crear un secreto directamente en el namespace de `argocd` con las credenciales SSH y etiquetarlo para que ArgoCD lo reconozca automáticamente como un repositorio.

**Comando utilizado en el servidor Linux:**
```bash
kubectl create secret generic hospital-repo-ssh -n argocd \
  --from-literal=type=git \
  --from-literal=url=git@github.com:WALDOHRA/Importar_Acreditados_SIS.git \
  --from-literal=sshPrivateKey="$(cat /home/vboxuser/.ssh/id_ed25519_gitops)" \
  && kubectl label secret hospital-repo-ssh -n argocd argocd.argoproj.io/secret-type=repository
```

---

## 2. Reestructuración de Manifiestos con Kustomize (Múltiples Ambientes)

**Objetivo:** Evolucionar de un despliegue básico (todo en `k8s/base/`) a una arquitectura empresarial que soporte entornos separados: Desarrollo (`dev`), Calidad (`qa`) y Producción (`prod`).

**Implementación:**
Kustomize, integrado de forma nativa en `kubectl`, fue utilizado para no duplicar código (DRY). Se dejó el código común en `base` y las variaciones en la carpeta `overlays`.

**Estructura de directorios creada:**
```text
k8s/
├── base/
│   ├── deployment.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml     # Añade el prefijo 'dev-', namespace 'importador-acreditados-dev'
    │   └── patch-ingress.yaml     # Define la URL dev.importa-sis...
    ├── qa/
    │   ├── kustomization.yaml     # Añade el prefijo 'qa-', namespace 'importador-acreditados-qa'
    │   └── patch-ingress.yaml     # Define la URL qa.importa-sis...
    └── prod/
        └── kustomization.yaml     # Despliega en namespace 'importador-acreditados-prod' sin alteración de nombres
```

---

## 3. Integración Continua (CI) con GitHub Actions

**Objetivo:** Automatizar la construcción (build) de la imagen Docker en cada cambio, y que ArgoCD lo detecte sin intervención manual.

**Implementación:**
Se creó el archivo `.github/workflows/ci-cd.yaml`.

El workflow de CI/CD realiza lo siguiente al hacer un `git push` a `main`:
1.  **Construye la imagen Docker** de la aplicación.
2.  **Genera etiquetas (tags):** Utiliza los primeros 7 caracteres del hash del commit (Ej. `sha-f5a1b32`) y la etiqueta `latest`.
3.  **Sube (Pushes) la imagen:** La publica en el registro de GitHub Container Registry (`ghcr.io`).
4.  **Auto-Actualiza Kustomize:** El bot clona el repositorio, y mediante el comando `kustomize edit set image`, actualiza agresivamente la etiqueta en `k8s/overlays/dev/kustomization.yaml` usando la versión del nuevo commit, y finalmente hace un `git push` encubierto (Auto-Commit).

**Resolución de Problemas (Troubleshooting) del Pipeline:**
1.  **Bloqueo Inicial:** El pipeline no arrancaba. Se solventó quitando los filtros de carpetas estrictos (`paths`) temporálmente y añadiendo el disparador `workflow_dispatch` al YAML para permitir ejecuciones manuales por primera vez.
2.  **Error `permission_denied: write_package`:** GitHub denegaba la subida porque detectaba un conflicto de nombres (las mayúsculas del repositorio VS letras estandarizadas de la imagen Docker).
    - *Corrección:* Se actualizaron los manifiestos `k8s/base/deployment.yaml` y `ci-cd.yaml` para usar explícitamente y en minúsculas `waldohra/importar_acreditados_sis:latest` (con guiones bajos en lugar de medios). Esto forzó al registro a enlazarse correctamente al repositorio en GitHub Packages autorizando su escritura automatizada.

---

## 4. Orquestación del Flujo de Despliegue (ArgoCD)

**Objetivo:** Configurar ArgoCD para que orqueste la infraestructura separando las carpetas lógicas en las distintas Aplicaciones estandarizadas.

**Instrucciones creadas para aplicar en el Servidor:**
1.  Borrar la vieja app genérica (`hospital-sis-app`).
2.  Crear **tres entidades independientes en ArgoCD**:
    -   `importador-acreditados-dev` apuntando a `k8s/overlays/dev`.
    -   `importador-acreditados-qa` apuntando a `k8s/overlays/qa`.
    -   `importador-acreditados-prod` apuntando a `k8s/overlays/prod`.
3.  Todas utilizan la política `Automated Sync`, con `Prune` habilitado (para limpiar recursos obsoletos) y la opción `CreateNamespace=true` (ArgoCD le indica a Kubernetes que cree el namespace si no existe todavía).

---

## 5. Mejores Prácticas Adoptadas: Resumen del Flujo GitOps resultantes

*   El programador escribe código.
*   Al hacer un `push` a GitHub, **Actions** levanta un servidor temporal, crea el contendor y lo sube.
*   El **Bot de Actions** realiza un commit alterando `kustomization.yaml` del ambiente **dev**.
*   **ArgoCD** detecta ese cambio provocado por el bot, y actualiza los pods en el clúster local K3s.
*   Todo sin interrupción del servicio y trazabilidad absoluta sobre qué versión exacta de software (SHA del commit) está corriendo en vivo.

**Limpieza final en GitHub:** Se identificó y eliminó un paquete de Docker antiguo (`importa-acreditados-sis` con guiones medios) a través de los settings web de GitHub para dejar únicamente el paquete oficial del repositorio con guiones bajos (`importar_acreditados_sis`).
