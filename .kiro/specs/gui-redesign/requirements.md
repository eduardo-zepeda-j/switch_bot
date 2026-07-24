# Requirements Document

## Introduction

Rediseño de la interfaz gráfica PyQt6 de Switch_bot para resolver cuatro problemas fundamentales: (1) la configuración de credenciales AWS Bedrock no es accesible ni clara, (2) el descubrimiento y selección de modelos locales (Ollama/llama.cpp) es difícil, (3) la aplicación no puede iniciar sesiones sin hardware ATEM/OBS conectado, y (4) el diseño visual no aprovecha plenamente el design system Catppuccin Mocha definido para broadcast. El rediseño mantiene la arquitectura existente (MainWindow + GuiBridge + Coordinator) y aplica el design system profesional ya definido, mejorando la usabilidad sin cambiar la lógica de negocio.

## Glossary

- **MainWindow**: Ventana principal PyQt6 que contiene todos los controles de sesión, selectores de backend IA, indicadores de tally, y configuración del sistema.
- **Panel_Configuración_Bedrock**: Panel expandible dentro de la GUI que expone las opciones de configuración de credenciales y región de AWS Bedrock.
- **Panel_Modelos_Locales**: Panel expandible que muestra los modelos locales descubiertos dinámicamente desde Ollama o llama.cpp, con información de tamaño y estado.
- **Modo_Standalone**: Modo de operación de Switch_bot donde la sesión se inicia sin requerir conexión a hardware ATEM ni OBS, operando solo con los pipelines de metadata y EDL.
- **Panel_Colapsable**: Widget QGroupBox o QToolBox personalizado que permite expandir/contraer secciones de configuración para mantener la interfaz limpia.
- **Sección_Hardware**: Área de la GUI que agrupa la configuración opcional de ATEM y OBS con indicadores visuales de estado de conexión.
- **StatusBadge**: Widget visual que combina un StatusDot con texto descriptivo del estado de un servicio o hardware.
- **Descubrimiento_Modelos**: Proceso automático o manual de consultar los modelos disponibles en un backend local (Ollama/llama.cpp) y presentarlos al operador.
- **Design_System**: Conjunto de reglas visuales basadas en Catppuccin Mocha adaptado para broadcast, definido en el steering del proyecto.

## Requirements

### Requirement 1: Panel de Configuración de AWS Bedrock

**User Story:** Como operador de producción, quiero tener un panel claro y accesible para configurar las credenciales y región de AWS Bedrock, para poder conectarme al servicio sin buscar en menús ocultos o archivos de configuración externos.

#### Acceptance Criteria

1. WHEN el operador selecciona "AWS Bedrock" como Backend_IA, THE Panel_Configuración_Bedrock SHALL expandirse automáticamente mostrando los campos de configuración: AWS Access Key ID (máximo 128 caracteres), AWS Secret Access Key (máximo 128 caracteres), región de AWS, y profile name opcional (máximo 64 caracteres).
2. WHEN el operador selecciona "Backend Local" como Backend_IA, THE Panel_Configuración_Bedrock SHALL contraerse automáticamente ocultando los campos de credenciales AWS.
3. THE Panel_Configuración_Bedrock SHALL enmascarar los campos de AWS Secret Access Key con caracteres de ocultación (bullet/asterisco) por defecto, con un botón toggle para revelar el valor.
4. THE Panel_Configuración_Bedrock SHALL permitir al operador ingresar un profile name de AWS como alternativa a las credenciales manuales (Access Key + Secret Key), deshabilitando los campos de credenciales manuales cuando el profile name contiene texto, y deshabilitando el campo de profile name cuando los campos de credenciales manuales contienen texto.
5. THE Panel_Configuración_Bedrock SHALL persistir las credenciales configuradas entre reinicios de la aplicación almacenándolas en el sistema de configuración local sin guardar el AWS Secret Access Key en texto plano.
6. WHEN el operador presiona el botón "Validar" con Bedrock seleccionado, THE Panel_Configuración_Bedrock SHALL deshabilitar el botón "Validar" y mostrar un indicador de carga, verificar la accesibilidad de AWS Bedrock con las credenciales proporcionadas dentro de un timeout máximo de 10 segundos, y mostrar el resultado mediante el StatusDot (verde=válido, rojo=fallo con mensaje indicando la causa), rehabilitando el botón al completar la verificación.
7. IF las credenciales AWS están vacías y no hay profile name configurado al intentar validar, THEN THE Panel_Configuración_Bedrock SHALL mostrar un mensaje de error inline indicando que se requiere un profile name o credenciales manuales.
8. IF la validación de credenciales AWS falla por timeout o error de red, THEN THE Panel_Configuración_Bedrock SHALL mostrar el StatusDot en rojo con un mensaje indicando que no se pudo conectar al servicio dentro del tiempo límite, y SHALL permitir al operador reintentar la validación sin recargar el panel.

### Requirement 2: Descubrimiento y Selección de Modelos Locales

**User Story:** Como operador de producción, quiero ver claramente qué modelos locales están disponibles en mi máquina (Ollama/llama.cpp) con información relevante de cada uno, para seleccionar el más adecuado sin necesidad de usar la terminal.

#### Acceptance Criteria

1. WHEN el operador selecciona "Backend Local" como Backend_IA, THE Panel_Modelos_Locales SHALL expandirse automáticamente mostrando los controles de descubrimiento de modelos.
2. WHEN el operador presiona el botón "Descubrir Modelos" o selecciona "Backend Local" por primera vez, THE MainWindow SHALL consultar el runtime local (Ollama o llama.cpp) con un timeout máximo de 10 segundos y poblar las listas de modelos de embeddings y modelos LLM con los modelos detectados.
3. THE Panel_Modelos_Locales SHALL mostrar cada modelo descubierto con su nombre identificador y su tamaño en GB en el dropdown de selección; si el tamaño no está disponible para un modelo, SHALL mostrarlo solo con su nombre identificador sin indicación de tamaño.
4. IF el runtime local (Ollama/llama.cpp) no responde dentro del timeout de 10 segundos o rechaza la conexión al consultar modelos, THEN THE Panel_Modelos_Locales SHALL mostrar un mensaje indicando el nombre del runtime seleccionado, que no está disponible, y la acción sugerida de iniciar el servicio correspondiente.
5. THE Panel_Modelos_Locales SHALL incluir un selector de tipo de runtime (Ollama o llama.cpp) para que el operador indique qué sistema de modelos locales utiliza.
6. WHEN el Descubrimiento_Modelos completa y detecta al menos 1 modelo, THE Panel_Modelos_Locales SHALL indicar la cantidad total de modelos encontrados con un StatusBadge en estado verde.
7. THE Panel_Modelos_Locales SHALL permitir al operador ejecutar un nuevo descubrimiento de modelos en cualquier momento mediante un botón de refresco, sin necesidad de cambiar de backend.
8. IF el runtime local está ejecutándose pero retorna 0 modelos disponibles, THEN THE Panel_Modelos_Locales SHALL mostrar un mensaje indicando que no se encontraron modelos instalados en el runtime y sugerir instalar modelos antes de continuar.

### Requirement 3: Operación en Modo Standalone (Sin Hardware)

**User Story:** Como operador de producción, quiero poder iniciar una sesión sin tener conectado un switcher ATEM ni OBS Studio, para usar Switch_bot como herramienta de anotación y generación de EDL sin depender de hardware externo.

#### Acceptance Criteria

1. THE MainWindow SHALL presentar los campos de ATEM IP y OBS URL como opcionales, utilizando un checkbox o toggle explícito "Habilitar ATEM" y "Habilitar OBS" que indique visualmente su carácter opcional.
2. WHEN los toggles de ATEM y OBS están desactivados, THE MainWindow SHALL permitir al operador iniciar sesión sin intentar conexión a ATEM ni OBS, ejecutando únicamente los pipelines Metadata y EDL.
3. WHEN el toggle de ATEM está desactivado, THE Sección_Hardware SHALL deshabilitar visualmente el campo IP ATEM (texto en gris, no editable) para indicar que no se utilizará.
4. WHEN el toggle de OBS está desactivado, THE Sección_Hardware SHALL deshabilitar visualmente el campo URL OBS (texto en gris, no editable) para indicar que no se utilizará.
5. WHEN la sesión se inicia sin hardware ATEM ni OBS habilitado, THE MainWindow SHALL mostrar un indicador de "Modo Standalone" visible en la barra superior durante toda la sesión.
6. WHILE la sesión opera en Modo_Standalone, THE MainWindow SHALL mantener funcionales los indicadores de tally mostrando la cámara seleccionada por el Motor_Decisión sin enviar comandos a hardware externo.
7. THE MainWindow SHALL persistir el estado de los toggles de hardware y los valores de los campos IP/URL entre reinicios de la aplicación.
8. IF el operador activa un toggle de hardware (ATEM u OBS) e intenta iniciar sesión con el campo de conexión correspondiente vacío, THEN THE MainWindow SHALL impedir el inicio de sesión y mostrar un mensaje indicando que el campo de conexión es requerido cuando el toggle está activo.
9. WHEN el operador activa solo uno de los toggles (ATEM o OBS), THE MainWindow SHALL permitir iniciar sesión conectando únicamente al hardware habilitado mientras el otro pipeline de hardware permanece inactivo.

### Requirement 4: Diseño Visual Profesional según Design System

**User Story:** Como operador de producción, quiero que la interfaz aplique completamente el design system Catppuccin Mocha adaptado para broadcast, para tener una experiencia visual coherente, profesional y cómoda durante sesiones de producción largas.

#### Acceptance Criteria

1. THE MainWindow SHALL aplicar la paleta de colores Catppuccin Mocha definida en el Design_System a todos los widgets visibles: base (#1e1e2e) como background principal de QMainWindow y QWidget, mantle (#181825) para headers, barras y panel lateral, surface0 (#313244) para panels, cards y QGroupBox, surface1 (#45475a) para widgets elevados (QPushButton, QComboBox), y text (#cdd6f4) como color de texto principal.
2. THE MainWindow SHALL utilizar paneles colapsables (Panel_Colapsable) para las secciones de configuración (Backend IA, Configuración Bedrock, Modelos Locales, Hardware), donde cada panel inicia en estado colapsado por defecto, se expande al hacer clic en su encabezado, y preserva su estado expandido/colapsado durante la sesión activa.
3. THE MainWindow SHALL aplicar un espaciado uniforme de 8px entre widgets y márgenes de 16px en contenedores, según la guía de layout del Design_System.
4. THE MainWindow SHALL mostrar el Panic_Button con el estilo prominente definido en el Design_System: fondo rojo (#f38ba8), texto oscuro (#1e1e2e), borde de 3px, border-radius de 12px, mínimo 60px de alto y 120px de ancho, font-size 14pt y font-weight bold.
5. THE MainWindow SHALL respetar las zonas de layout del Design_System: zona principal (70% del ancho) con tally, timecode y controles de sesión; panel lateral (30% del ancho) con configuración y notas, aplicándose a partir de un ancho mínimo de ventana de 1024px.
6. THE MainWindow SHALL usar la fuente monoespaciada con orden de preferencia JetBrains Mono, Fira Code, Consolas (fallback), color cyan (#94e2d5) y tamaño 14pt para el TimecodeDisplay según la especificación del Design_System.
7. THE MainWindow SHALL estilizar todos los QComboBox, QLineEdit, QTextEdit y QPushButton según el stylesheet base QSS del Design_System, incluyendo los estados :hover (border-color #89b4fa), :pressed (background #89b4fa con texto #1e1e2e), :disabled (opacidad reducida) y :focus (border-color #89b4fa).
8. THE MainWindow SHALL incluir tooltips en todos los botones y controles interactivos, donde cada tooltip contiene la descripción de la acción y el atajo de teclado asociado entre paréntesis (por ejemplo: "Pausar automatización (F12)"), cumpliendo la directriz de accesibilidad del Design_System.
9. THE MainWindow SHALL garantizar un ratio de contraste mínimo de 4.5:1 (WCAG AA) entre el texto principal y su fondo en todos los widgets, y SHALL complementar la información transmitida por color con texto o iconos para indicadores de estado (por ejemplo: texto "ON AIR" junto al color rojo del tally).

### Requirement 5: Reorganización del Layout Principal

**User Story:** Como operador de producción, quiero que la información más importante (tally, timecode, panic) sea lo más visible y accesible, y que la configuración se organice de forma lógica en paneles colapsables, para operar eficientemente durante la producción.

#### Acceptance Criteria

1. THE MainWindow SHALL organizar la zona principal (70% izquierda, mínimo 700px de ancho) con la siguiente jerarquía vertical de arriba a abajo: (1) barra superior con timecode + estado de sesión + panic button, (2) indicadores de tally para las 4 cámaras, (3) controles de sesión (botones iniciar/detener) visibles sin necesidad de scroll.
2. THE MainWindow SHALL organizar el panel lateral (30% derecha, mínimo 300px de ancho) con paneles colapsables en el siguiente orden de arriba a abajo: (1) Backend IA y modelos, (2) Configuración Hardware (IP ATEM, URL OBS, directorio de salida, modo de video), (3) Notas y Prompts de IA (campo de texto y botones de envío).
3. THE MainWindow SHALL posicionar los controles de inicio/parada de sesión en la zona principal, inmediatamente debajo de los indicadores de tally, garantizando que sean visibles sin scroll vertical en resoluciones de 1280x720 o superiores.
4. WHEN un panel colapsable se contrae, THE MainWindow SHALL reducir su alto visual a únicamente la barra de título (máximo 36px de alto), liberando espacio vertical para los demás paneles del panel lateral.
5. WHEN un panel colapsable se expande, THE MainWindow SHALL mostrar su contenido completo con una animación de expansión de 150ms de duración utilizando una curva de easing ease-in-out.
6. THE MainWindow SHALL mostrar los paneles de Backend IA y Configuración Hardware expandidos por defecto al abrir la aplicación, y el panel de Notas y Prompts de IA contraído.
7. THE MainWindow SHALL preservar el estado de expansión/contracción de cada panel entre reinicios de la aplicación, restaurando el último estado guardado al abrir la ventana.
8. WHEN el operador hace clic en la barra de título de un panel colapsable, THE MainWindow SHALL alternar el estado del panel entre expandido y contraído.

### Requirement 6: Feedback Visual de Estado de Conexiones

**User Story:** Como operador de producción, quiero ver de un vistazo el estado de todas las conexiones del sistema (Bedrock, Ollama, ATEM, OBS), para saber rápidamente si algo no está conectado antes de iniciar la sesión.

#### Acceptance Criteria

1. THE MainWindow SHALL mostrar un StatusBadge (StatusDot + texto) para cada servicio configurable: Backend IA, ATEM, y OBS.
2. WHEN el estado de conexión de un servicio cambia, THE MainWindow SHALL actualizar su StatusBadge correspondiente en un tiempo inferior a 100ms para garantizar feedback inmediato al operador.
3. THE MainWindow SHALL usar los colores del Design_System para cada estado de conexión: verde (#a6e3a1) para conectado, amarillo (#f9e2af) para reconectando, rojo (#f38ba8) para desconectado, y gris (#585b70) para deshabilitado.
4. WHILE ATEM o OBS están deshabilitados por toggle, THE MainWindow SHALL mostrar su StatusBadge en estado "deshabilitado" (gris) con texto "No configurado" en lugar de "Desconectado".
5. THE MainWindow SHALL agrupar todos los StatusBadges de conexiones en un área de resumen visual ubicada en la barra superior de la ventana principal, visible sin necesidad de navegación adicional.
6. THE MainWindow SHALL complementar el color de cada StatusBadge con un texto descriptivo del estado que corresponda a: "Conectado" para el estado conectado, "Reconectando..." para el estado reconectando, "Desconectado" para el estado desconectado, y "No configurado" para el estado deshabilitado.
7. WHEN la aplicación inicia y aún no se ha intentado conexión con un servicio, THE MainWindow SHALL mostrar el StatusBadge de dicho servicio en estado "desconectado" (rojo) con texto "Desconectado" hasta que se establezca la conexión o se deshabilite el servicio.
