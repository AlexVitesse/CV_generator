# CV Generator — Harvard Format

Un generador de CV profesional con formato estilo Harvard, construido con **Streamlit**, **ReportLab** y análisis de vacantes con IA.

## ✨ Características

### Edición y formato
- **Edición en tiempo real**: Modifica tus datos directamente en la interfaz.
- **Formato Harvard**: Genera un PDF limpio, profesional y optimizado para ATS.
- **Sección de Proyectos**: Agrega proyectos con nombre, URL y descripción con métricas.
- **Importación JSON**: Importa datos de CV desde archivo JSON.
- **Traducción automática**: Traduce todo el contenido del CV entre Español e Inglés con un clic (vía Google Translate), incluyendo etiquetas de skills ("Core skills" / "Dominio avanzado").
- **Interfaz bilingüe**: Toda la UI disponible en Español e Inglés.

### Análisis con IA
- **Análisis de vacante**: Pega el texto de una vacante y obtén match score, keywords que coinciden/faltan, y sugerencias de adaptación editables.
- **Chat de refinamiento**: Chat inline en el tab de Análisis para decirle a la IA sobre experiencia que no está en tu CV. La IA pregunta detalles y al re-analizar incorpora el contexto extra.
- **Score Navbar**: Puntuación del último análisis siempre visible en la parte superior + botón para re-evaluar.
- **Asesor de CV (Chat)**: Chat interactivo con IA para redactar bullets, agregar experiencia no documentada y recibir feedback honesto.
- **Evaluación detallada**: Dashboard con barras por dimensión, requisitos uno por uno, detección de overfitting y veredictos accionables.
- **Auto-traducción inteligente**: Al aplicar adaptaciones, si la vacante está en otro idioma, auto-traduce el CV antes de re-evaluar.
- **Anti-overfitting**: Reglas estrictas contra inflación de experiencia, keyword stuffing y fabricación de hechos.
- **Post-procesamiento**: Limpieza automática de problemas comunes de la IA (palabras pegadas, paréntesis justificativos, mezcla de idiomas).
- **Inferencia técnica**: Detecta dependencias implícitas (FastAPI → Pydantic, RunPod → Docker) sin inventar.

### Generación de contenido
- **Summary / Elevator Pitch**: Genera un resumen profesional de ~60 palabras adaptado a la vacante, listo para copiar al portapapeles.
- **Cover Letter**: Genera una carta de presentación personalizada usando el CV, la vacante y el nombre de la empresa como contexto.

### Banco de habilidades
- **Banco de habilidades y proyectos**: Master set con todas tus experiencias, bullets, proyectos, skills y educación. Activa/desactiva items según la vacante sin perder datos.
- **Selección con IA**: La IA selecciona automáticamente los items más relevantes del banco para una vacante.

## 🚀 Instalación

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

Para usar las funciones de análisis con IA necesitas una API key de [Ollama Cloud](https://ollama.com):

1. Obtén tu API key en la plataforma de Ollama.
2. En la barra lateral de la app, ingresa tu API key y modelo (por defecto: `minimax-m2.7:cloud`).
3. La configuración se guarda localmente en `.ai_config.json` (excluido de git).

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
2. Tab **Análisis**: pega vacante → analiza → navbar muestra score (ej. "68%")
3. Revisa sugerencias, edítalas → clic "Aplicar adaptaciones" → auto-traduce si es necesario → re-evalúa
4. **Refinar análisis**: abre el chat inline → cuéntale a la IA experiencia extra → re-analiza con contexto
5. Tab **Asesor**: pregunta al chat sobre redacción de bullets o feedback general
6. Tab **Evaluación**: genera evaluación detallada con barras, requisitos y veredictos
7. Tab **Banco**: gestiona tu master set de habilidades, activa/desactiva items por vacante
8. Sidebar: genera **Summary** o **Cover Letter** → copia al portapapeles
9. Genera PDF con nombre de empresa y descarga

## 📄 Licencia
Este proyecto es de código abierto.
