# CV Generator — Harvard Format

Un generador de CV profesional con formato estilo Harvard, construido con **Streamlit**, **ReportLab** y traducción automática integrada.

## ✨ Características
- **Edición en tiempo real**: Modifica tus datos directamente en la interfaz.
- **Traducción automática**: Traduce todo el contenido del CV entre Español e Inglés con un clic (vía Google Translate gratuito).
- **Formato Harvard**: Genera un PDF limpio, profesional y optimizado para ATS.
- **Importación/Exportación**: Guarda tus datos en formato JSON para editarlos después.

## 🚀 Instalación

1. Clona este repositorio.
2. Crea un entorno virtual y actívalo:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```
3. Instala las dependencias:
   ```bash
   pip install streamlit reportlab deep-translator
   ```

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

## 📄 Licencia
Este proyecto es de código abierto. ¡Siéntete libre de usarlo y mejorarlo!
