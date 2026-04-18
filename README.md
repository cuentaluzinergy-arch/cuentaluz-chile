# ⚡ CuentaLuz Chile

Calculadora de boleta eléctrica residencial para Chile. Permite estimar el desglose real de la cuenta de luz según distribuidora (Enel, CGE, Chilquinta, Frontel) y tarifa (BT1 / BT2).

## Funcionalidades

- **Calculadora principal**: ingreso directo de kWh o estimación por aparatos
- **Desglose de boleta**: cargo fijo, energía, distribución e IVA
- **Gráfico interactivo**: torta del desglose con Chart.js
- **Escenarios de ahorro**: impacto de reducir 10 %, 20 % y 30 % el consumo
- **Análisis solar**: retorno de inversión simplificado para paneles fotovoltaicos
- **Comparador BT1 vs BT2**: para decidir si conviene cambiar de tarifa
- **Recomendaciones personalizadas**: 3 acciones concretas según el perfil de consumo
- **Newsletter**: captura de emails en SQLite

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Jinja2 |
| Frontend | HTML + Tailwind CDN + Chart.js CDN |
| Base de datos | SQLite (SQLAlchemy) |
| Deploy | Railway / Render |

## Estructura del proyecto

```
cuenta-luz-chile/
├── main.py                        # App FastAPI, filtros Jinja2, entry point
├── database.py                    # Configuración SQLAlchemy
├── requirements.txt
├── Procfile                       # Para Railway/Render
├── railway.toml                   # Config Railway
├── .env.example
├── config/
│   ├── tarifas.json               # Tarifas por distribuidora ← editar aquí
│   └── aparatos.json              # Lista de electrodomésticos
├── app/
│   ├── models/subscriber.py       # Modelo SQLAlchemy para newsletter
│   ├── routes/
│   │   ├── calculator.py          # Rutas GET / y POST /calcular
│   │   └── newsletter.py          # Ruta POST /api/newsletter
│   └── services/
│       └── calculator_service.py  # Lógica de negocio (pura, sin HTTP)
├── templates/
│   ├── base.html                  # Layout base con header/footer
│   ├── index.html                 # Formulario calculadora
│   └── resultados.html            # Página de resultados
└── static/
    ├── css/custom.css
    └── js/main.js                 # Tabs, contador kWh, validación
```

## Instalación local

```bash
# 1. Clonar / descargar el proyecto
cd cuenta-luz-chile

# 2. Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar
python main.py
# o bien:
uvicorn main:app --reload

# 5. Abrir en el navegador
# http://localhost:8000
```

## Deploy en Railway

1. Subir el proyecto a un repositorio GitHub.
2. En Railway: **New Project → Deploy from GitHub repo**.
3. Railway detecta automáticamente el `Procfile` o el `railway.toml`.
4. (Opcional) Agregar variable de entorno `DATABASE_URL` con una URL PostgreSQL para producción.

## Deploy en Render

1. Crear un nuevo **Web Service** apuntando al repositorio.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Actualizar tarifas

Las tarifas están en `config/tarifas.json`. Edita los valores `cargo_fijo_clp`, `cargo_energia_clp_kwh` y `cargo_distribucion_clp_kwh` según los decretos tarifarios vigentes de la CNE.

## Monetización (preparado, no implementado)

- **AdSense**: busca los comentarios `<!-- ADSENSE PLACEHOLDER -->` en `base.html` e `index.html` e inserta tu código de unidad de anuncio.
- **Afiliados solares**: busca el comentario `<!-- AFILIADOS -->` en `resultados.html`.

## Licencia

MIT — úsalo libremente para proyectos personales o comerciales.
