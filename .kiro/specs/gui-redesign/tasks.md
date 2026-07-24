# Implementation Plan: GUI Redesign

## Overview

Rediseño incremental de la GUI PyQt6 de Switch_bot: nuevos widgets reutilizables (CollapsiblePanel, StatusBadge), paneles de configuración especializados (BedrockConfigPanel, LocalModelsPanel, HardwareSection), reorganización del layout MainWindow con persistencia via QSettings, extensión del GuiBridge, y actualización del theme/stylesheet. Se implementa en Python 3.11+ con PyQt6, validado con pytest + hypothesis.

## Tasks

- [x] 1. Create reusable base widgets (CollapsiblePanel, StatusBadge, utilities)
  - [x] 1.1 Implement CollapsiblePanel widget
    - Create `switch_bot/gui/collapsible_panel.py`
    - Implement `CollapsiblePanel(QWidget)` with `toggled` signal, animated expand/collapse via `QPropertyAnimation` on `maximumHeight` (150ms, InOutQuad)
    - Header: clickable bar (max 36px) with rotatable chevron icon + title label
    - Methods: `is_expanded()`, `set_expanded(expanded, animate=True)`, `set_content(widget)`, `title()`
    - Apply design system styling (surface0 background, surface1 border, subtext0 title color)
    - _Requirements: 5.4, 5.5, 5.8_

  - [x] 1.2 Implement StatusBadge widget
    - Create `switch_bot/gui/status_badge.py`
    - Implement `BadgeState` enum (CONNECTED, RECONNECTING, DISCONNECTED, DISABLED)
    - Implement `StatusBadge(QWidget)` composing existing `StatusDot` + `QLabel` in horizontal layout
    - Map states to colors: green=#a6e3a1, yellow=#f9e2af, red=#f38ba8, grey=#585b70
    - Map states to text: "Conectado", "Reconectando...", "Desconectado", "No configurado"
    - Methods: `set_state(state)`, `state()`
    - _Requirements: 6.1, 6.3, 6.6_

  - [x] 1.3 Implement secret obfuscation utilities
    - Create `switch_bot/gui/credentials.py`
    - Implement `obfuscate_secret(secret: str) -> str` using base64 + byte reversal
    - Implement `deobfuscate_secret(stored: str) -> str` reversing the obfuscation
    - Implement `ModelInfo` dataclass with `id`, `name`, `size_gb`, `model_type`, `display_text()` method
    - _Requirements: 1.5, 2.3_

  - [x] 1.4 Write property tests for CollapsiblePanel toggle (Property 6)
    - **Property 6: CollapsiblePanel toggle inverts state**
    - **Validates: Requirements 5.8**
    - Use `@given(st.booleans())` for initial state, verify `set_expanded(not state)` inverts `is_expanded()`

  - [x] 1.5 Write property tests for StatusBadge state mapping (Property 7)
    - **Property 7: StatusBadge state mapping correctness**
    - **Validates: Requirements 6.3, 6.6**
    - Use `@given(st.sampled_from(BadgeState))` to verify correct color and non-empty text for every state

  - [x] 1.6 Write property tests for secret obfuscation and ModelInfo (Properties 2, 3)
    - **Property 2: Secret obfuscation round-trip**
    - **Validates: Requirements 1.5**
    - Use `@given(st.text(min_size=1, alphabet=printable_chars))` to verify `deobfuscate(obfuscate(s)) == s`
    - **Property 3: Model display text formatting**
    - **Validates: Requirements 2.3**
    - Use `@given(st.builds(ModelInfo, ...))` to verify display_text contains name and optional size

- [x] 2. Implement BedrockConfigPanel
  - [x] 2.1 Create BedrockConfigPanel widget
    - Create `switch_bot/gui/bedrock_config_panel.py`
    - Implement `BedrockConfigPanel(QWidget)` with signals: `credentials_changed()`, `validate_requested()`
    - Fields: AWS Access Key ID (QLineEdit, max 128), AWS Secret Access Key (QLineEdit, EchoMode.Password + visibility toggle), Region (QComboBox with standard regions), Profile Name (QLineEdit, max 64)
    - Implement mutual exclusion logic: profile_name text → disable access_key/secret_key; access_key/secret_key text → disable profile_name
    - Implement `get_credentials() -> dict`, `set_validation_state(state, message)`, `set_validating(bool)`
    - Implement `load_settings(QSettings)` and `save_settings(QSettings)` with secret obfuscation
    - Apply design system styling, tooltips for all interactive controls
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 2.2 Write property test for credential mutual exclusion (Property 1)
    - **Property 1: Credential mutual exclusion**
    - **Validates: Requirements 1.4**
    - Use `@given(st.text(min_size=1))` to verify that setting profile disables manual fields, and vice versa

  - [x] 2.3 Write unit tests for BedrockConfigPanel
    - Test visibility toggle for secret key field
    - Test validation state transitions (loading, success, error)
    - Test empty credentials error message (Req 1.7)
    - _Requirements: 1.3, 1.6, 1.7, 1.8_

- [ ] 3. Implement LocalModelsPanel
  - [ ] 3.1 Create LocalModelsPanel widget
    - Create `switch_bot/gui/local_models_panel.py`
    - Implement `LocalModelsPanel(QWidget)` with signals: `discover_requested()`, `runtime_changed(str)`, `model_selected(str, str)`
    - Fields: Runtime selector QComboBox ["Ollama", "llama.cpp"], Discover button + refresh button, Embedding model QComboBox, LLM model QComboBox, StatusBadge for model count
    - Methods: `set_runtime(str)`, `populate_models(embeddings, llms)`, `set_discovering(bool)`, `set_error(message)`, `set_status(count)`
    - Display model name + size in GB format via `ModelInfo.display_text()`
    - Apply design system styling, tooltips for all interactive controls
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [-] 3.2 Write unit tests for LocalModelsPanel
    - Test `populate_models` with concrete model data
    - Test error state display when runtime unavailable
    - Test runtime selector changes
    - Test zero-models message (Req 2.8)
    - _Requirements: 2.2, 2.4, 2.6, 2.8_

- [ ] 4. Implement HardwareSection
  - [ ] 4.1 Create HardwareSection widget
    - Create `switch_bot/gui/hardware_section.py`
    - Implement `HardwareSection(QWidget)` with signals: `atem_toggled(bool)`, `obs_toggled(bool)`, `config_changed()`
    - Layout: QCheckBox "Habilitar ATEM" + IP field (disabled when toggle off), QCheckBox "Habilitar OBS" + URL field (disabled when toggle off), output directory with browse button, video mode selector
    - Methods: `is_atem_enabled()`, `is_obs_enabled()`, `get_atem_ip()`, `get_obs_url()`, `get_output_dir()`, `get_video_mode()`, git`validate_for_session() -> tuple[bool, str]`
    - Implement `load_settings(QSettings)` and `save_settings(QSettings)`
    - Apply design system styling, tooltips for all interactive controls
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.7, 3.8, 3.9_

  - [ ] 4.2 Write property test for hardware session validation (Property 4)
    - **Property 4: Hardware session validation**
    - **Validates: Requirements 3.2, 3.8, 3.9**
    - Use `@given(st.booleans(), st.booleans(), st.text(), st.text())` to verify validation logic for all toggle/field combinations

  - [ ] 4.3 Write unit tests for HardwareSection
    - Test toggle enable/disable of fields (Req 3.3, 3.4)
    - Test validate_for_session with empty fields and active toggle (Req 3.8)
    - Test persistence load/save (Req 3.7)
    - _Requirements: 3.3, 3.4, 3.7, 3.8_

- [ ] 5. Checkpoint - Ensure all widget tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Reorganize MainWindow layout with new components
  - [ ] 6.1 Refactor MainWindow to integrate new widgets
    - Modify `switch_bot/gui/main_window.py`
    - Replace `_build_backend_section` with CollapsiblePanel containing BedrockConfigPanel + LocalModelsPanel (auto-expand/collapse based on backend selection)
    - Replace `_build_config_section` with CollapsiblePanel containing HardwareSection
    - Wrap notes section in CollapsiblePanel (collapsed by default)
    - Move session controls (start/stop) to main area below tally indicators
    - Add StatusBadges (IA, ATEM, OBS) to the top bar area
    - Maintain 70/30 splitter layout (min 700px main, min 300px side)
    - Add `standalone_mode_active` signal, `set_standalone_mode()` method
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.5_

  - [ ] 6.2 Implement UI state persistence with QSettings
    - Add `save_ui_state()` and `restore_ui_state()` methods to MainWindow
    - Persist: panel expanded/collapsed states, hardware toggles, field values, backend type, last selected models
    - Call `restore_ui_state()` in `__init__` and `save_ui_state()` on close event
    - Use QSettings key prefix "gui-redesign/v1"
    - _Requirements: 3.7, 5.7, 1.5_

  - [ ] 6.3 Write property test for UI state persistence round-trip (Property 5)
    - **Property 5: UI state persistence round-trip**
    - **Validates: Requirements 3.7, 5.7**
    - Use `@given(st.fixed_dictionaries(...))` to verify save/load produces equivalent state

  - [ ] 6.4 Write smoke tests for MainWindow layout
    - Verify splitter sizes (70/30)
    - Verify StatusBadges exist in top bar
    - Verify session controls are in main area
    - Verify all CollapsiblePanels are present with correct default states
    - _Requirements: 5.1, 5.2, 5.3, 5.6, 6.5_

- [ ] 7. Extend GuiBridge for new signals
  - [ ] 7.1 Extend GuiBridge with new signal handlers
    - Modify `switch_bot/gui/gui_bridge.py`
    - Add slot `_on_validate_bedrock()` connected to BedrockConfigPanel.validate_requested
    - Add slot `_on_discover_models()` connected to LocalModelsPanel.discover_requested
    - Add slot `_on_hardware_toggled(service, enabled)` connected to HardwareSection toggles
    - Add method `update_service_status(service: str, state: BadgeState)` to update StatusBadges
    - Connect all new widget signals in `_connect_signals()`
    - _Requirements: 1.6, 2.2, 3.1_

  - [ ] 7.2 Write unit tests for GuiBridge extensions
    - Test signal routing from BedrockConfigPanel to coordinator mock
    - Test signal routing from LocalModelsPanel to coordinator mock
    - Test service status update propagates to StatusBadges
    - _Requirements: 1.6, 2.2, 6.2_

- [ ] 8. Update theme and stylesheet
  - [ ] 8.1 Update theme.py with new QSS selectors
    - Modify `switch_bot/gui/theme.py`
    - Add QCheckBox styling (Catppuccin colors for checked/unchecked states)
    - Add CollapsiblePanel header styling (mantle background, clickable cursor)
    - Add StatusBadge styling (horizontal layout spacing)
    - Add QSS for disabled state visual feedback on all new widgets
    - Ensure all foreground/background pairs maintain WCAG 4.5:1 contrast ratio
    - _Requirements: 4.1, 4.3, 4.7, 4.9_

  - [ ] 8.2 Write property test for WCAG contrast compliance (Property 8)
    - **Property 8: WCAG contrast ratio compliance**
    - **Validates: Requirements 4.9**
    - Use `@given(st.sampled_from(color_pairs))` over theme color pairs to verify >= 4.5:1 ratio

- [ ] 9. Update module exports and wiring
  - [ ] 9.1 Update gui package exports
    - Modify `switch_bot/gui/__init__.py`
    - Export new widgets: `CollapsiblePanel`, `StatusBadge`, `BadgeState`, `BedrockConfigPanel`, `LocalModelsPanel`, `HardwareSection`, `ModelInfo`
    - Export utility functions: `obfuscate_secret`, `deobfuscate_secret`
    - _Requirements: 1.1, 2.1, 3.1, 6.1_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests validate the 8 universal correctness properties defined in the design
- Unit/smoke tests validate specific examples and edge cases
- The design uses Python (PyQt6) directly — implementation language is Python 3.11+
- Existing widgets (TallyIndicator, StatusDot, TimecodeDisplay, ConnectionState) are reused, not rewritten
- QSettings persistence uses INI format with "gui-redesign/v1" key prefix
- Secret obfuscation is minimal (base64 + reversal) — not cryptographic

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.5", "1.6", "2.1", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "4.2", "4.3"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1", "8.1"] },
    { "id": 5, "tasks": ["6.3", "6.4", "7.2", "8.2", "9.1"] }
  ]
}
```
