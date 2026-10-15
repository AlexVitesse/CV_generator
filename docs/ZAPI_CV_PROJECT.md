# ZAPI - Plataforma SaaS de Ventas por WhatsApp con IA

**Rol:** Fundador & Full-Stack Developer
**Periodo:** 2026 - Presente
**URL:** [zapi.click](https://zapi.click)

---

## Descripcion del Proyecto

Plataforma SaaS multi-tenant que automatiza la atencion al cliente y ventas por WhatsApp usando agentes de IA conversacional. Los negocios (restaurantes, tiendas) conectan su WhatsApp, suben su menu y el bot atiende clientes 24/7: toma pedidos, procesa pagos, valida comprobantes y gestiona entregas.

---

## Stack Tecnologico

### Backend
- **Python 3.11 + FastAPI** - API REST async con SQLAlchemy 2.0
- **PostgreSQL 16** con pgvector para busqueda semantica
- **Redis** - Pub/Sub para mensajeria en tiempo real, cache, sesiones
- **Alembic** - Migraciones de base de datos (26+ migraciones)
- **Gunicorn + Uvicorn** - Servidor ASGI multi-worker

### Frontend
- **React 18 + TypeScript** - SPA con Vite
- **TailwindCSS** - Diseño responsivo mobile-first
- **React Router** - Navegacion SPA
- **Axios** - Cliente HTTP con interceptors de auth

### Inteligencia Artificial
- **LangChain** - Framework de agentes con ReAct pattern
- **Groq API** (gpt-oss-120b) - LLM para conversacion natural
- **Google Gemini 2.5 Flash** - Vision AI para:
  - Extraccion automatica de menus desde imagenes/PDF
  - Validacion de comprobantes de pago (OCR + analisis)
- **OpenAI Whisper** (via Groq) - Transcripcion de notas de voz
- **Embeddings** (sentence-transformers) - Busqueda semantica en base de conocimiento

### WhatsApp Integration
- **Node.js + Express** - Gateway de WhatsApp
- **Baileys 6.7.21** - Cliente WhatsApp Web no oficial
- **Multi-sesion** - Soporte para multiples negocios simultaneos
- **Debouncing** - Acumulacion inteligente de mensajes rapidos
- **Anti-ban** - Simulacion de comportamiento humano (typing, lectura, delays aleatorios)

### Infraestructura
- **Docker + Docker Compose** - Contenedorizacion de 4 servicios
- **Cloudflare Tunnel** - Exposicion segura sin IP publica
- **Cloudflare R2** - Almacenamiento de imagenes (logos, productos)
- **Supabase Auth** - Autenticacion con Google OAuth + email
- **Servidor fisico Debian** - Deployment on-premise

---

## Arquitectura

```
Cliente WhatsApp → Baileys (Node.js) → Redis Pub/Sub → AI Core (Python)
                                                           ↓
                                                    LangChain Agent
                                                    ↓           ↓
                                                 Groq LLM    Gemini Vision
                                                    ↓
                                              20+ Tool Functions
                                              (cart, orders, payments...)
                                                    ↓
                                               PostgreSQL
```

### Servicios:
- **ai-core** - Backend Python (API + Worker de mensajes + Agente IA)
- **wa-service** - Gateway WhatsApp (Node.js + Baileys)
- **postgres** - Base de datos con pgvector
- **redis** - Cache, sesiones, pub/sub

---

## Desarrollo de Agentes de IA

### Sales Agent (Agente de Ventas)
- Patron **ReAct** (Reason + Act) con LangChain
- **20+ herramientas** (tools) especializadas:
  - `greet_customer` - Saludo personalizado
  - `get_menu` - Mostrar catalogo (texto o URL digital)
  - `add_to_cart` / `add_multiple_to_cart` - Gestion de carrito
  - `remove_from_cart` / `update_cart_item` - Modificaciones
  - `view_cart` - Resumen del pedido
  - `create_order` - Crear orden con validacion de datos
  - `process_payment` - Procesar pago (efectivo/transferencia)
  - `validate_payment_proof` - Validar comprobante con Gemini Vision
  - `get_delivery_zones` / `check_delivery_availability` - Zonas de entrega
  - `search_knowledge` - RAG sobre base de conocimiento
  - `suggest_complement` / `get_upselling_suggestions` - Ventas cruzadas
  - `get_business_info` / `get_delivery_hours` - Informacion del negocio

### System Prompt Engineering
- Prompt dinamico que se adapta por tenant (nombre, tipo de negocio, productos)
- 3 niveles de intensidad de ventas (Low/Medium/High)
- Reglas criticas para evitar: loops, alucinaciones, pedidos vacios
- Deteccion de frustracion del cliente → escalacion al negocio
- Manejo de ubicacion GPS, notas de voz, imagenes

### Evaluacion con Dataset
- **Taskmaster-1** (Google Research) - 20 dialogos de pedidos traducidos al español
- Score: **89%** (19/20 pasaron, 10 perfectas)
- Escenarios: pedido simple, modificaciones, cancelaciones, cliente frustrado, producto no encontrado, multiples items, cambio de cantidad, GPS, horarios, transferencia

---

## Menu Digital Interactivo

Menu web tipo OlaClick/DiDi Food accesible via URL unica por negocio.

### Caracteristicas:
- **Diseño OlaClick-style**: Banner + logo sobresaliente + info card
- **Catalogo de productos** con categorias, busqueda, imagenes de Unsplash
- **Detalle de producto**: imagen grande, descripcion, comentarios, cantidad
- **Carrito**: resumen, subtotal + envio = total
- **Checkout completo**: nombre, telefono, domicilio/recoger, direccion estructurada (calle, num ext, num int, colonia, referencia)
- **Zonas de entrega** con costo configurable por colonia
- **Validacion de pedido minimo** para delivery
- **Color personalizable** por negocio (color picker + bloqueo de colores claros)
- **Horarios** de atencion con badge Abierto/Cerrado
- **Envio por WhatsApp** con mensaje pre-armado completo (datos del cliente + pedido + envio)
- **Responsive** mobile-first con font Poppins

---

## Sistema de Pagos y Validacion

### Metodos de pago:
- **Efectivo** - Confirmacion directa
- **Transferencia bancaria** - Muestra datos (CLABE, banco, beneficiario)
- **MercadoPago** - Checkout integrado con webhooks

### Validacion de comprobantes con IA:
- **Flujo determinista** (sin LLM): imagen + orden pendiente → Gemini Vision directo
- Gemini extrae: monto, banco, beneficiario, fecha, hora
- Validacion: monto debe coincidir (±1%), fecha = hoy, hora > creacion de orden
- Cuenta/CLABE ignorada (bancos truncan a ultimos 4 digitos)
- Costo: ~$0.01 USD por validacion

---

## Multi-Tenancy y Dashboard

### Modelo multi-tenant:
- Un usuario puede gestionar multiples negocios
- Cada negocio tiene: configuracion de bot, productos, pedidos, clientes, analytics
- Aislamiento completo de datos entre tenants

### Dashboard incluye:
- **Onboarding** guiado (4 pasos) con sistema de cupones para trials
- **Productos** con infinite scroll, categorias colapsables, renombrar en batch, upload de menu con IA
- **Pedidos** con detalle, Google Maps link, estado
- **Configuracion de bot** (horarios, mensajes, intensidad de ventas)
- **Zonas de entrega** con costo por colonia
- **Analytics** de creditos, mensajes, conversiones
- **Planes y suscripciones** con trial automatico (14 dias via cupon)
- **Menu Digital** con color picker, slug personalizable, vista previa

---

## Sistema de Creditos

- Texto enviado por bot = 1 credito
- Audio transcrito (Whisper) = 3 creditos
- Imagen procesada (Gemini) = 2 creditos
- Mensajes del cliente = 0 creditos
- Expiracion automatica de trials
- Separacion de API keys: FREE (pilotos/demos) vs PAID (clientes que pagan)

---

## DevOps y Operaciones

- **Docker Compose** para desarrollo y produccion
- **Backups automaticos** a USB (cron 4 AM) + BD encriptada
- **Auditorias DBA**: VACUUM, indices, vistas, retencion de datos
- **Healthchecks** cada 5 min con watchdog
- **Rate limiting** por usuario y anti-spam
- **Deduplicacion** de mensajes con Redis SETNX atomico
- **Logging** de tokens Groq + Gemini con costo estimado
- **Seguridad**: sanitizacion de input, proteccion contra prompt injection

---

## Metricas

| Metrica | Valor |
|---------|-------|
| Lineas de codigo | ~15,000+ (Python + TypeScript + Node.js) |
| Tablas en BD | 38 |
| Migraciones | 26 |
| Tools del agente | 20+ |
| Score evaluacion IA | 89% (Taskmaster-1) |
| Costo por pedido (LLM) | ~$0.004 USD (free keys) |
| Costo por validacion (Gemini) | ~$0.01 USD |
| Uptime | 99%+ |

---

## Competencia Analizada

- **OlaClick** - Menu digital + WhatsApp ordering (50,000+ restaurantes LATAM)
- **MasPedidos** - POS + menu digital (1,300+ negocios Mexico)
- **Diferenciador ZAPI**: IA conversacional real vs bots de arbol de decisiones
