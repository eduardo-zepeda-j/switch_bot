"""Diálogo de sugerencias publicitarias post-sesión.

Presenta al operador las 3 sugerencias publicitarias generadas por el
IAEnricher al finalizar una sesión de grabación, con timecodes de
referencia y texto propuesto en formato legible.

Requisitos: 17.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from switch_bot.gui.theme import BASE_STYLESHEET, COLORS

if TYPE_CHECKING:
    from switch_bot.ia.ia_enricher import AdSuggestion


class AdSuggestionsDialog(QDialog):
    """Diálogo modal que presenta sugerencias publicitarias post-sesión.

    Muestra 3 sugerencias con:
    - Timecodes de referencia (tc_in → tc_out) en fuente monoespaciada
    - Texto propuesto para cada espacio publicitario
    - Score de relevancia como barra visual con porcentaje

    Sigue el sistema de diseño Catppuccin Mocha broadcast del proyecto.

    Requisitos: 17.5
    """

    def __init__(
        self,
        suggestions: list[AdSuggestion],
        parent: QWidget | None = None,
    ) -> None:
        """Inicializa el diálogo con la lista de sugerencias.

        Args:
            suggestions: Lista de AdSuggestion (se muestran hasta 3).
            parent: Widget padre (normalmente MainWindow).
        """
        super().__init__(parent)
        self._suggestions = suggestions[:3]
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Construye la interfaz del diálogo."""
        self.setWindowTitle("Sugerencias Publicitarias — Post-Sesión")
        self.setMinimumWidth(560)
        self.setModal(True)
        self.setStyleSheet(BASE_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Header
        header = QLabel("📺 Sugerencias Publicitarias")
        header.setObjectName("sectionHeader")
        header.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['cyan']}; padding-bottom: 8px;")
        layout.addWidget(header)

        subtitle = QLabel(
            "Espacios publicitarios sugeridos según el análisis de la sesión"
        )
        subtitle.setStyleSheet(f"color: {COLORS['subtext0']}; font-size: 9pt;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Suggestion cards
        if self._suggestions:
            for idx, suggestion in enumerate(self._suggestions, start=1):
                card = self._build_suggestion_card(idx, suggestion)
                layout.addWidget(card)
        else:
            empty_label = QLabel("No se generaron sugerencias para esta sesión.")
            empty_label.setStyleSheet(f"color: {COLORS['subtext0']};")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty_label)

        layout.addSpacing(8)

        # Close button
        close_btn = QPushButton("Cerrar")
        close_btn.setToolTip("Cerrar el diálogo de sugerencias publicitarias")
        close_btn.setFixedWidth(120)
        close_btn.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _build_suggestion_card(
        self, index: int, suggestion: AdSuggestion
    ) -> QFrame:
        """Construye una tarjeta visual para una sugerencia individual.

        Args:
            index: Número de la sugerencia (1-3).
            suggestion: Datos de la sugerencia publicitaria.

        Returns:
            QFrame con el layout de la tarjeta.
        """
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ "
            f"  background-color: {COLORS['surface0']}; "
            f"  border: 1px solid {COLORS['surface1']}; "
            f"  border-radius: 8px; "
            f"  padding: 12px; "
            f"}}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        # Top row: index badge + timecodes
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # Index badge
        badge = QLabel(f"#{index}")
        badge.setStyleSheet(
            f"background-color: {COLORS['magenta']}; "
            f"color: {COLORS['crust']}; "
            f"font-weight: bold; "
            f"border-radius: 4px; "
            f"padding: 2px 8px; "
            f"font-size: 9pt;"
        )
        badge.setFixedWidth(32)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(badge)

        # Timecodes
        tc_in_str = suggestion.tc_in.to_string()
        tc_out_str = suggestion.tc_out.to_string()

        tc_label = QLabel(f"{tc_in_str}  →  {tc_out_str}")
        tc_label.setFont(
            QFont("JetBrains Mono", 10, QFont.Weight.Normal)
        )
        tc_label.setStyleSheet(f"color: {COLORS['cyan']};")
        tc_label.setToolTip("Timecodes de referencia (inicio → fin)")
        top_row.addWidget(tc_label)

        top_row.addStretch()
        card_layout.addLayout(top_row)

        # Suggestion text
        text_label = QLabel(suggestion.text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(
            f"color: {COLORS['text']}; "
            f"font-size: 10pt; "
            f"padding: 4px 0px;"
        )
        card_layout.addWidget(text_label)

        # Relevance score row
        score_row = QHBoxLayout()
        score_row.setSpacing(8)

        score_label = QLabel("Relevancia:")
        score_label.setStyleSheet(
            f"color: {COLORS['subtext0']}; font-size: 9pt;"
        )
        score_row.addWidget(score_label)

        # Progress bar for relevance score
        score_bar = QProgressBar()
        score_bar.setRange(0, 100)
        score_bar.setValue(int(suggestion.relevance_score * 100))
        score_bar.setFixedHeight(14)
        score_bar.setTextVisible(False)
        score_bar.setStyleSheet(
            f"QProgressBar {{ "
            f"  background-color: {COLORS['surface1']}; "
            f"  border: none; "
            f"  border-radius: 7px; "
            f"}} "
            f"QProgressBar::chunk {{ "
            f"  background-color: {COLORS['green']}; "
            f"  border-radius: 7px; "
            f"}}"
        )
        score_bar.setToolTip(
            f"Score de relevancia: {suggestion.relevance_score:.0%}"
        )
        score_row.addWidget(score_bar, stretch=1)

        pct_label = QLabel(f"{suggestion.relevance_score:.0%}")
        pct_label.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 9pt; font-weight: bold;"
        )
        score_row.addWidget(pct_label)

        card_layout.addLayout(score_row)

        return card
