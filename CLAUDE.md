# DocIntake — Contexto del proyecto para Claude

## Quién soy y para qué es esto
Soy Luca. DocIntake es una plataforma de automatización de ingesta de documentos para estudios jurídicos de EE. UU. (litigios y lesiones personales). Este proyecto tiene dos objetivos, en este orden:

1. **Aprender de verdad**: quiero entender cada pieza, no solo tener código que funciona.
2. **Tener un proyecto de portfolio** que muestre un stack backend de producción: Python/FastAPI, PostgreSQL, RabbitMQ, Celery, Docker, CI/CD, tests y observabilidad.

Plazo: ~4 semanas, avanzando de a poco.

## Cómo quiero que trabajes conmigo
- **Paso a paso.** Una tarea chica por vez. No generes el proyecto entero de golpe.
- **Antes de codear, explicá el plan** en 3-5 líneas: qué vamos a hacer, por qué y qué concepto nuevo aparece.
- **Explicá los conceptos nuevos** (ej. idempotencia, dead-letter queue, migraciones) brevemente y con un ejemplo del proyecto.
- **Dejame escribir partes a mí** cuando sea un buen ejercicio: proponé el esqueleto o los tests y yo completo la implementación. Después revisá mi código como en un code review real.
- **Tests primero cuando tenga sentido** (TDD), sobre todo en lógica de negocio (clasificación, matching, reglas).
- **Al terminar cada paso**: decime cómo probarlo, sugerí un mensaje de commit (Conventional Commits, en inglés) y cuál es el siguiente paso.
- Si algo tiene trade-offs, mostrame las opciones y por qué elegís una. Quiero poder defender cada decisión técnica.
- Respondeme en **español**. El **código, comentarios, commits, README y docs van en inglés**.
- Mantené actualizada la sección **"Estado actual"** al final de este archivo cuando terminemos un paso.

## Qué es DocIntake
Recibir documentos legales/médicos, entenderlos y archivarlos automáticamente en el caso correcto.

### Flujo
```
Upload / email ──► FastAPI ──► Postgres (documento: received)
                      │
                      └──► RabbitMQ ──► Celery workers:
                                         1. OCR / extracción de texto
                                         2. Clasificación (tipo de documento)
                                         3. Extracción de entidades (partes, fechas, proveedor médico, nº de caso)
                                         4. Matching con el caso (matter)
                                         5. Aplicar reglas del estudio (nombre, carpeta, routing)
                                         6. Alertas por fechas límite
                                      ──► Postgres (filed / needs_review)
                                      ──► Dashboard React (bandeja, revisión humana)
```

### Estados del documento
`received → text_extracted → classified → entities_extracted → matched → filed`
Desde cualquier etapa: `→ needs_review` (baja confianza) o `→ failed` (error tras reintentos).

### Tipos de documento (inicial)
`medical_record`, `medical_bill`, `pleading`, `correspondence`, `discovery_request`, `lien_notice`, `other`

## Stack
| Área | Herramienta |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2 |
| DB | PostgreSQL, SQLAlchemy 2.0, Alembic |
| Mensajería / async | RabbitMQ, Celery, Flower |
| Procesamiento | pdfplumber / pytesseract, rapidfuzz, LLM o scikit-learn para clasificación |
| Frontend | React + Vite + TypeScript (simple) |
| Tests | pytest, pytest-cov, testcontainers, httpx |
| Calidad | ruff, mypy, pre-commit |
| DevOps | Docker, docker-compose, GitHub Actions |
| Observabilidad | logs JSON (structlog) con correlation_id, Prometheus + Grafana |
| Gestión de dependencias | uv |

## Principios
- **Datos sintéticos únicamente.** Nada de documentos reales (simulamos PHI/HIPAA).
- **Tareas idempotentes**: procesar dos veces el mismo documento no duplica resultados.
- **Reintentos con backoff** y **dead-letter queue** para fallos permanentes.
- **Multi-tenant**: cada estudio (`firm`) solo ve sus datos.
- **Configuración por variables de entorno** (pydantic-settings), nunca secretos en el repo.
- **Nada de datos sensibles en logs.**
- Código modular: separar `api/`, `domain/` (lógica pura, fácil de testear), `workers/`, `db/`.

## Estructura de carpetas (objetivo)
```
docintake/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── .github/workflows/ci.yml
├── docs/
│   ├── architecture.md
│   └── adr/                # Architecture Decision Records
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/            # routers FastAPI
│   │   ├── domain/         # clasificación, matching, reglas (sin dependencias de infra)
│   │   ├── db/             # modelos y repositorios
│   │   ├── workers/        # app Celery y tareas
│   │   └── observability/
│   └── tests/
│       ├── unit/
│       └── integration/
├── scripts/
│   └── generate_fake_docs.py
└── frontend/
```

## Roadmap (marcar con [x] al completar)

### Semana 1 — Base
- [ ] 1.1 Repo, estructura, `uv`, ruff, mypy, pre-commit
- [ ] 1.2 FastAPI hello world + `/health` + primer test
- [ ] 1.3 Docker + docker-compose (api + postgres)
- [ ] 1.4 SQLAlchemy + Alembic: modelos `Firm`, `Matter`, `Document`
- [ ] 1.5 Endpoint de upload de PDF + listado de documentos
- [ ] 1.6 GitHub Actions: lint + tests
- [ ] 1.7 Script de generación de PDFs sintéticos

### Semana 2 — Procesamiento asíncrono
- [ ] 2.1 RabbitMQ + Celery en docker-compose, primera tarea
- [ ] 2.2 Tarea de extracción de texto (OCR) + cambio de estado
- [ ] 2.3 Encadenar etapas del pipeline (chain)
- [ ] 2.4 Reintentos, backoff, dead-letter queue, estado `failed`
- [ ] 2.5 Idempotencia
- [ ] 2.6 Tests de integración con testcontainers
- [ ] 2.7 Flower para monitorear workers

### Semana 3 — Inteligencia y producto
- [ ] 3.1 Clasificador (TDD) con puntaje de confianza
- [ ] 3.2 Extracción de entidades (fechas, partes, proveedor, nº de caso)
- [ ] 3.3 Matching de caso con rapidfuzz
- [ ] 3.4 Reglas configurables por estudio (naming / routing)
- [ ] 3.5 Cola `needs_review` + endpoints de revisión humana
- [ ] 3.6 Frontend React: bandeja, detalle, revisión

### Semana 4 — Producción
- [ ] 4.1 Auth JWT + aislamiento multi-tenant
- [ ] 4.2 Logs estructurados con correlation_id
- [ ] 4.3 Métricas Prometheus + dashboard Grafana
- [ ] 4.4 Benchmark: throughput con 1 vs N workers
- [ ] 4.5 README, diagrama de arquitectura, 2-3 ADRs
- [ ] 4.6 Deploy + video demo de 2 minutos

### Extras (si sobra tiempo)
- [ ] Cronología médica con cita a la página de origen
- [ ] Mock de API tipo Clio y conector que "empuja" documentos archivados
- [ ] Ingesta por email (IMAP o webhook)

## Repaso semanal
Al terminar cada semana, ayudame a repasar (en inglés):
- Cómo explicar lo que construí en 1-2 minutos.
- 3 preguntas técnicas probables sobre lo que hicimos y cómo responderlas.
- Los trade-offs que elegimos y sus alternativas.

## Estado actual
- **Paso actual:** 1.1 en curso. Archivos creados; falta instalar `uv`, correr `uv sync` y `pre-commit install` y hacer el primer commit.
- **Decisiones tomadas:**
  - `pyproject.toml` vive en `backend/` (monorepo: backend y frontend separados, cada uno con su tooling).
  - Python fijado a 3.12 (`.python-version`); uv lo descarga solo, aunque el sistema tenga 3.14.
  - Backend como proyecto "virtual" de uv (no se empaqueta); pytest importa `app` vía `pythonpath = ["."]`.
  - Ruff y mypy corren en pre-commit como hooks **locales** (`uv run`), así usan las mismas versiones que `uv.lock` y CI.
  - mypy en modo `strict` desde el inicio.
  - `.gitattributes` fuerza LF (desarrollo en Windows, CI/Docker en Linux).
- **Pendientes / dudas:** —
- **Notas de aprendizaje:** —
