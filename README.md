# CV Generator — Harvard Format

Un generador de CV profesional con formato estilo Harvard, construido con **Streamlit**, **ReportLab** y análisis de vacantes con IA (Ollama · OpenAI · Anthropic · Gemini).

## ✨ Características

### Edición y formato
- **Edición en tiempo real**: Modifica tus datos directamente en la interfaz.
- **Formato Harvard**: Genera un PDF limpio, profesional y optimizado para ATS.
- **Sección de Proyectos**: Agrega proyectos con nombre, URL y descripción con métricas.
- **Importación JSON**: Importa datos de CV desde archivo JSON.
- **Traducción automática**: Traduce todo el contenido del CV entre Español e Inglés con un clic (vía Google Translate), incluyendo etiquetas de skills ("Core skills" / "Dominio avanzado").
- **Interfaz bilingüe**: Toda la UI disponible en Español e Inglés.

### Análisis con IA
- **Multi-proveedor**: Elige entre **Groq**, **Ollama Cloud**, **OpenAI**, **Anthropic (Claude)** o **Google Gemini** desde el sidebar. Cada proveedor guarda su propia API key y modelo; Groq (`openai/gpt-oss-120b`) es el default.
- **Análisis de vacante**: Pega el texto de una vacante y obtén match score, keywords que coinciden/faltan, y sugerencias de adaptación editables.
- **OCR de vacante (Gemini Vision)**: Sube una captura o foto de la vacante y extrae su texto automáticamente, sin pegarlo a mano. Requiere una API key de Gemini guardada.
- **Chat de refinamiento**: Chat inline en el tab de Análisis para decirle a la IA sobre experiencia que no está en tu CV. La IA pregunta detalles y al re-analizar incorpora el contexto extra.
- **Score Navbar**: Puntuación del último análisis siempre visible en la parte superior + botón para re-evaluar.
- **Asesor de CV (Chat)**: Chat interactivo con IA para redactar bullets, agregar experiencia no documentada y recibir feedback honesto.
- **Evaluación detallada**: Dashboard con barras por dimensión, requisitos uno por uno, detección de overfitting y veredictos accionables.
- **Auto-traducción inteligente**: Al aplicar adaptaciones, si la vacante está en otro idioma, auto-traduce el CV antes de re-evaluar.
- **Anti-overfitting**: Reglas estrictas contra inflación de experiencia, keyword stuffing y fabricación de hechos.
- **Guards anti-fabricación**: Al adaptar el CV se bloquea la invención de métricas inexistentes y la elevación de skills a un tier superior al respaldado por la evidencia.
- **Post-procesamiento**: Limpieza automática de problemas comunes de la IA (palabras pegadas, paréntesis justificativos, mezcla de idiomas).
- **Inferencia técnica**: Detecta dependencias implícitas (FastAPI → Pydantic, RunPod → Docker) sin inventar.

### Generación de contenido
- **Summary / Elevator Pitch**: Genera un resumen profesional de ~60 palabras adaptado a la vacante, listo para copiar al portapapeles.
- **Cover Letter**: Genera una carta de presentación personalizada usando el CV, la vacante y el nombre de la empresa como contexto.

### Banco de habilidades
- **Banco de habilidades y proyectos**: Master set con todas tus experiencias, bullets, proyectos, skills y educación. Activa/desactiva items según la vacante sin perder datos.
- **Selección con IA**: La IA selecciona automáticamente los items más relevantes del banco para una vacante.

## 🚀 Instalación

**Requisito:** Python 3.10 o superior (probado en 3.12).

1. Clona este repositorio.
2. Crea un entorno virtual y actívalo:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## 🔑 Configuración de IA

Las funciones de IA soportan cinco proveedores: Groq por defecto y los demás opcionales. Elige uno en el sidebar e ingresa su API key:

| Proveedor | Modelo default (editable) | Dónde obtener la key |
|-----------|---------------------------|----------------------|
| **Groq (default)** | `openai/gpt-oss-120b` | [console.groq.com](https://console.groq.com) |
| Ollama Cloud | `gpt-oss:120b-cloud` | [ollama.com](https://ollama.com) |
| OpenAI | `gpt-6.1-sol` | [platform.openai.com](https://platform.openai.com) |
| Anthropic (Claude) | `claude-opus-5-5` | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | `gemini-3.8-flash` | [aistudio.google.com](https://aistudio.google.com) |

1. En la barra lateral, elige el proveedor e ingresa su API key. El modelo se elige de una lista sugerida por proveedor (`MODEL_OPTIONS` en `cvgen/llm_client.py`) o se escribe cualquier otro id.
2. Cada proveedor conserva su propia key y modelo; puedes alternar sin perderlos.
3. La configuración se guarda localmente en `.ai_config.json` (excluido de git). Para Ollama, la variable de entorno `OLLAMA_API_KEY` tiene prioridad.
4. El **OCR de vacante** usa Gemini Vision, así que necesitas una key de Gemini guardada para habilitarlo (independientemente del proveedor activo).

## 🛠️ Configuración Personalizada

Para mantener tus datos personales seguros y no subirlos accidentalmente a GitHub:

1. El proyecto incluye un archivo `config_plantilla.json`.
2. Haz una copia de ese archivo y nómbrala `config_personal.json`.
3. Edita `config_personal.json` con tu información real.
4. El archivo `.gitignore` ya está configurado para ignorar `config_personal.json`, por lo que tus datos estarán a salvo localmente.

## 💻 Uso
Ejecuta la aplicación con:
```bash
streamlit run app.py
```

### Flujo típico
1. Carga tu CV (JSON o edición manual) → navbar muestra "—"
2. Tab **Análisis**: pega vacante (o súbela como imagen → OCR con Gemini) → analiza → navbar muestra score (ej. "68%")
3. Revisa sugerencias, edítalas → clic "Aplicar adaptaciones" → auto-traduce si es necesario → re-evalúa
4. **Refinar análisis**: abre el chat inline → cuéntale a la IA experiencia extra → re-analiza con contexto
5. Tab **Asesor**: pregunta al chat sobre redacción de bullets o feedback general
6. Tab **Evaluación**: genera evaluación detallada con barras, requisitos y veredictos
7. Tab **Banco**: gestiona tu master set de habilidades, activa/desactiva items por vacante
8. Sidebar: genera **Summary** o **Cover Letter** → copia al portapapeles
9. Genera PDF con nombre de empresa y descarga

## 📄 Licencia
Este proyecto es de código abierto.
