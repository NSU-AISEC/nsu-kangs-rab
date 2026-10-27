"""화면 색 토큰과 앱 전체 스타일 시트 (docs/visual-design.md 3절 · 8절).

Qt 위젯을 만들지 않는 순수 문자열 생성이다(`QApplication` 없이 시험할 수 있다).
"""
from __future__ import annotations

TOKENS = {
    "dark": {
        "canvas": "#07080A", "surface": "#0D0D0D", "surface-elevated": "#101111", "surface-card": "#121212",
        "hairline": "#242728", "hairline-strong": "rgba(255,255,255,0.16)",
        "ink": "#F4F4F6", "body": "#CDCDCD", "mute": "#9C9C9D", "ash": "#6A6B6C",
        "primary": "#FFFFFF", "primary-pressed": "#E8E8E8", "on-primary": "#000000",
        "info": "#57C1FF", "info-bg": "#182831", "error": "#FF6161", "error-bg": "#311A1A",
        "ok": "#59D499", "ok-bg": "#182B22", "warn": "#FFC533", "warn-bg": "#312913",
        "sb-track": "#1A1B1C", "sb-thumb": "#5A5C5E", "sb-hover": "#7A7C7E", "sb-press": "#9A9C9E",     # 7-14 어두운 화면
        "value-box": "#07080A", "accent": "#57C1FF", "accent-bg": "#182831",     # 7-10 값 표시 상자(어둡게 canvas), 지정 중 키캡(accent 는 info 를 쓴다)
    },
    "light": {
        "canvas": "#F6F6F7", "surface": "#FFFFFF", "surface-elevated": "#F0F0F2", "surface-card": "#E9E9EC",
        "hairline": "#E1E1E4", "hairline-strong": "rgba(0,0,0,0.16)",
        "ink": "#111113", "body": "#2F2F33", "mute": "#5E5E64", "ash": "#8A8A91",
        "primary": "#111113", "primary-pressed": "#2F2F33", "on-primary": "#FFFFFF",
        "info": "#0A6CB0", "info-bg": "#E2EDF6", "error": "#C42B2B", "error-bg": "#F8E6E6",
        "ok": "#13774A", "ok-bg": "#E3EFE9", "warn": "#8A5A00", "warn-bg": "#F1EBE0",
        "sb-track": "#F1F1F1", "sb-thumb": "#C1C1C1", "sb-hover": "#A8A8A8", "sb-press": "#787878",     # 7-14 밝은 화면(Chrome)
        "value-box": "#E9E9EC", "accent": "#0A6CB0", "accent-bg": "#E2EDF6",
    },
}

_TEMPLATE = """
QWidget {{ background: {canvas}; color: {body}; font-size: 14pt; }}
QFrame#card {{ background: {surface}; border: 1px solid {hairline}; border-radius: 10px; }}
QLineEdit, QPlainTextEdit, QComboBox {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline}; border-radius: 8px; padding: 8px 12px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {hairline-strong}; }}
QPushButton {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline}; border-radius: 8px; padding: 8px 16px; min-height: 20px; }}
QPushButton#primary {{ background: {primary}; color: {on-primary}; border: none; }}
QPushButton#primary:pressed {{ background: {primary-pressed}; }}
QPushButton[primary="true"] {{ background: {primary}; color: {on-primary}; border: none; }}
QPushButton[primary="true"]:pressed {{ background: {primary-pressed}; }}
QPushButton:disabled, QPushButton#primary:disabled {{ background: {surface-elevated}; color: {ash}; border: none; }}
QLabel#badge {{ background: {surface-elevated}; color: {body}; border-radius: 4px; padding: 2px 8px; font-size: 12pt; }}
QLabel#notice {{ background: {info-bg}; color: {info}; border-radius: 8px; padding: 8px 12px; }}
QLabel#warning {{ background: {warn-bg}; color: {warn}; border-radius: 8px; padding: 8px 12px; }}
QLabel#error {{ background: {error-bg}; color: {error}; border-radius: 8px; padding: 8px 12px; }}
QLabel#mute {{ background: transparent; color: {mute}; }}
QWidget#card_imgrow {{ background: transparent; }}
QLabel#card_question {{ background: transparent; color: {body}; }}
QLabel#card_caption {{ background: transparent; color: {mute}; font-size: 12px; }}
QLabel#card_thumb {{ background: transparent; border: 1px solid {hairline}; border-radius: 6px; }}
QLabel#about_image {{ border: 1px solid {hairline}; border-radius: 12px; }}
QLabel#about_title {{ background: transparent; color: {ink}; font-size: 24pt; font-weight: 700; }}
QLabel#about_subtitle {{ background: transparent; color: {mute}; font-size: 13pt; font-weight: 600; }}
QFrame#about_card {{ background: {surface}; border: 1px solid {hairline}; border-radius: 8px; }}
QFrame#about_card QLabel {{ background: transparent; color: {body}; font-size: 13pt; border: none; }}
QFrame#banner {{ background: {warn-bg}; border: none; border-bottom: 1px solid {hairline}; border-radius: 0; }}
QLabel#banner_title {{ background: transparent; color: {warn}; font-weight: 700; border: none; }}
QFrame#banner[tone="info"] {{ background: {info-bg}; }}
QLabel#banner_title[tone="info"] {{ color: {info}; }}
QFrame#card QLabel {{ background: transparent; color: {ink}; }}
QFrame#card QLabel#badge {{ background: {surface-elevated}; color: {body}; }}
QFrame#card QLabel#badge_error {{ background: {error-bg}; color: {error}; border-radius: 4px; padding: 2px 8px; font-size: 12pt; }}
QFrame#card QLabel#mute {{ color: {mute}; }}
QFrame#card QLabel#error {{ background: transparent; color: {ink}; padding: 0; }}
QPushButton#card_delete {{ background: transparent; color: {mute}; border: none; border-radius: 11px; padding: 0; min-height: 22px; min-width: 22px; }}
QPushButton#card_delete:pressed {{ background: {surface-elevated}; }}
QWidget#pane_left {{ background: {surface}; }}
QWidget#pane_right {{ background: {canvas}; }}
QFrame#pane_header {{ background: transparent; border: none; border-bottom: 1px solid {hairline}; }}
QLabel#pane_title {{ background: transparent; color: {ink}; font-weight: 600; }}
QLabel#pane_note {{ background: transparent; color: {mute}; font-size: 12pt; }}
QLabel#status_item_warn {{ background: transparent; color: {warn}; font-size: 12pt; }}
QLabel#status_item_info {{ background: transparent; color: {info}; font-size: 12pt; }}
QPushButton[transport="true"] {{ background: {surface-elevated}; border: 1px solid {hairline}; border-radius: 6px; padding: 0; min-height: 26px; min-width: 26px; }}
QPushButton[transport="true"]:disabled {{ border: 1px solid transparent; }}
QPushButton[transport="true"][emphasized="true"] {{ background: {primary}; border: 1px solid transparent; }}
QPushButton[headerbtn="true"] {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline}; border-radius: 6px; padding: 0 12px; min-height: 0; min-width: 0; font-size: 13pt; font-weight: 600; }}
QPushButton[headerbtn="true"]:disabled {{ background: {surface-elevated}; color: {ash}; border: 1px solid {hairline}; }}
QPushButton[keybtn="true"] {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline}; border-radius: 6px; padding: 0 10px; min-height: 0; min-width: 0; font-size: 12px; font-weight: 500; }}
QPushButton[keybtn="true"]:disabled {{ background: {surface-elevated}; color: {ash}; border: 1px solid {hairline}; }}
QPushButton#btn_reflect[transport="true"]:disabled {{ border: 1px solid {hairline}; }}
QPushButton#btn_capture[transport="true"]:disabled {{ border: 1px solid {hairline}; }}
QLabel#chip_paused {{ background: {warn-bg}; color: {warn}; border-radius: 4px; padding: 2px 8px; font-size: 11pt; font-weight: 600; }}
QLabel#chip_before {{ background: {info-bg}; color: {info}; border-radius: 4px; padding: 2px 8px; font-size: 11pt; font-weight: 600; }}
QFrame#transcript_guide {{ background: transparent; border: 1px dashed {hairline-strong}; border-radius: 12px; margin: 14px 20px; }}
QFrame#transcript_guide QLabel {{ background: transparent; border: none; }}
QLabel#transcript_guide_title {{ color: {ink}; font-weight: 600; }}
QLabel#transcript_guide_body {{ color: {mute}; font-size: 13px; }}
QFrame#transcript_guide[state="error"] {{ background: {error-bg}; border: 1px solid {error}; }}
QFrame#transcript_guide[state="error"] QLabel#transcript_guide_title {{ color: {error}; }}
QLabel#transcript_guide_permission {{ background: transparent; color: {info}; font-size: 12px; }}
QLabel#ai_guide {{ background: transparent; color: {mute}; }}
QLabel#card_question {{ background: transparent; color: {body}; }}
QListWidget#transcript {{ background: {surface}; color: {ink}; border: none; outline: none; }}
QScrollArea#ai_view {{ background: {canvas}; border: none; }}
QWidget#ai_inner {{ background: {canvas}; }}
QWidget#input_area {{ background: {canvas}; border-top: 1px solid {hairline}; }}
QWidget#chip_box, QWidget#edit_box {{ background: transparent; }}
QSplitter#main_split::handle {{ background: {hairline}; }}
QLabel#banner_text {{ background: transparent; color: {body}; font-size: 12pt; border: none; }}
QStatusBar {{ background: {canvas}; color: {mute}; border-top: 1px solid {hairline}; font-size: 12pt; }}
QStatusBar::item {{ border: none; }}
QWidget#status_box {{ background: transparent; }}
QLabel#status_pill {{ background: {info-bg}; color: {info}; border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 500; }}
QLabel#status_pill_warn {{ background: {warn-bg}; color: {warn}; border-radius: 4px; padding: 2px 8px; font-size: 12px; }}
QLabel#status_item {{ background: transparent; color: {mute}; font-size: 12pt; }}
QPushButton#iconbtn {{ background: transparent; color: {body}; border: 1px solid {hairline}; border-radius: 6px; padding: 0; min-height: 26px; min-width: 26px; }}
QPushButton#iconbtn:pressed {{ background: {surface-card}; }}
QPushButton#iconbtn:disabled {{ background: transparent; color: {ash}; border: 1px solid {hairline}; }}
QFrame#level_on {{ background: {ok}; border: none; }}
QFrame#level_off {{ background: {hairline}; border: none; }}
QFrame#level_stopped {{ background: {mute}; border: none; }}
QLabel#section_title {{ background: transparent; color: {ink}; font-weight: 600; }}
QComboBox#prov_combo {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline-strong}; border-radius: 8px; padding: 0 36px 0 12px; font-weight: 600; min-height: 34px; }}
QComboBox#prov_combo::drop-down {{ border: none; width: 0px; }}
QComboBox#prov_combo::down-arrow {{ image: none; width: 0px; }}
QListView#prov_view {{ background: {surface}; border: 1px solid {hairline-strong}; border-radius: 8px; outline: 0; padding: 0; }}
QFrame#doc_panel {{ background: {surface}; border: 1px solid {hairline}; border-radius: 10px; }}
QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {mute}; background: transparent; }}
QRadioButton::indicator:checked {{ width: 6px; height: 6px; border: 5px solid {ink}; background: {surface}; }}
QRadioButton::indicator:disabled {{ border: 1px solid {ash}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {mute}; background: transparent; }}
QCheckBox::indicator:checked {{ background: {ink}; border: 1px solid {ink}; }}
QCheckBox::indicator:disabled {{ border: 1px solid {ash}; }}
QFrame#doc_panel QLabel {{ background: transparent; }}
QFrame#first_key_row {{ background: {surface-elevated}; border: none; border-radius: 8px; }}
QFrame#key_row {{ background: transparent; border: none; }}
QRadioButton#choice_plain {{ background: transparent; color: {ink}; border: none; padding: 0; spacing: 8px; font-weight: 400; }}
QRadioButton#choice_plain:checked {{ font-weight: 600; }}
QRadioButton#choice_plain:disabled {{ color: {ash}; }}
QLabel#keycap {{ background: {surface-card}; color: {ink}; border: 1px solid {hairline}; border-radius: 4px; padding: 4px 10px; font-weight: 500; }}
QLabel#set_keycap {{ background: {value-box}; color: {ink}; border: none; border-radius: 6px; padding: 0 10px; min-width: 56px; font-weight: 500; }}
QLabel#set_keycap[state="empty"] {{ background: transparent; color: {mute}; border: 1px dashed {hairline-strong}; font-weight: 400; }}
QLabel#set_keycap[state="capturing"] {{ background: {accent-bg}; color: {accent}; border: 1px solid {accent}; }}
QFrame#doc_panel QLabel#set_keycap {{ background: {value-box}; color: {ink}; border: none; border-radius: 6px; padding: 0 10px; min-width: 56px; font-weight: 500; }}
QFrame#doc_panel QLabel#set_keycap[state="empty"] {{ background: transparent; color: {mute}; border: 1px dashed {hairline-strong}; font-weight: 400; }}
QFrame#doc_panel QLabel#set_keycap[state="capturing"] {{ background: {accent-bg}; color: {accent}; border: 1px solid {accent}; }}
QPushButton#set_keybtn {{ border: 1px solid {hairline}; border-radius: 8px; padding: 0 14px; min-height: 30px; }}
QPushButton#set_keybtn[muted="true"] {{ color: {mute}; }}
QFrame#doc_panel QLabel#key_hint {{ background: transparent; color: {mute}; font-size: 12px; }}
QFrame#doc_panel QLabel#key_warn {{ background: {warn-bg}; color: {warn}; font-size: 12px; border: none; border-radius: 0; padding: 6px 14px; min-height: 18px; }}
QLabel#panel_note {{ background: transparent; color: {mute}; font-size: 12pt; }}
QPushButton#danger {{ color: {error}; }}
QPushButton#danger:disabled {{ color: {ash}; }}
QFrame#template_card {{ background: {surface-elevated}; border: 1px solid {hairline}; border-radius: 10px; }}
QWidget#template_zone, QWidget#template_buttons {{ background: transparent; }}
QLabel#template_cap {{ background: transparent; color: {mute}; font-size: 12px; font-weight: 600; }}
QLabel#template_cap[focused="true"] {{ color: {ink}; }}
QFrame#template_divider {{ background: {hairline}; border: none; }}
QFrame#template_divider[focused="true"] {{ background: {hairline-strong}; }}
QPlainTextEdit#template_edit, QPlainTextEdit#template_edit:focus {{ background: transparent; color: {ink}; border: none; border-radius: 0; padding: 0; font-family: Menlo, monospace; font-size: 12px; }}
QLabel#end_title {{ background: transparent; color: {ink}; font-size: 17pt; font-weight: 600; }}
QLabel#end_sub {{ background: transparent; color: {mute}; }}
QLabel#end_path {{ background: transparent; color: {mute}; font-size: 12pt; }}
QLabel#end_name {{ background: transparent; color: {ink}; font-family: Menlo; }}
QLabel#end_note {{ background: transparent; color: {mute}; font-size: 12pt; }}
QLabel#end_pill_ok {{ background: {ok-bg}; color: {ok}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QLabel#end_pill_warn {{ background: {warn-bg}; color: {warn}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QLabel#end_pill_run {{ background: {info-bg}; color: {info}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QLabel#end_pill_bad {{ background: {error-bg}; color: {error}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QProgressBar#end_progress {{ background: {surface-elevated}; border: none; border-radius: 4px; max-height: 6px; min-height: 6px; }}
QLabel#end_progress_text {{ background: transparent; color: {mute}; font-size: 12px; }}
QProgressBar#end_progress::chunk {{ background: {ink}; border-radius: 4px; }}
QFrame#doc_panel QLabel#end_pill_ok {{ background: {ok-bg}; color: {ok}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QFrame#doc_panel QLabel#end_pill_warn {{ background: {warn-bg}; color: {warn}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QFrame#doc_panel QLabel#end_pill_run {{ background: {info-bg}; color: {info}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QFrame#doc_panel QLabel#end_pill_bad {{ background: {error-bg}; color: {error}; border-radius: 4px; font-size: 11pt; font-weight: 500; }}
QLabel#fr_title {{ background: transparent; color: {ink}; font-size: 26pt; font-weight: 700; }}
QLabel#fr_sub {{ background: transparent; color: {mute}; font-size: 13pt; font-weight: 600; }}
QLabel#fr_h2 {{ background: transparent; color: {ink}; font-size: 18pt; font-weight: 700; }}
QFrame#start_check_dot {{ background: {ok}; border: none; border-radius: 4px; }}
QFrame#claude_note_dot {{ background: {ok}; border: none; border-radius: 4px; }}
QFrame#claude_note_dot[tone="warn"] {{ background: {warn}; }}
QLabel#start_check_text {{ background: transparent; color: {mute}; font-size: 12pt; }}
QFrame#start_banner {{ background: {error-bg}; border: 1px solid {error}; border-radius: 8px; }}
QLabel#start_banner_title {{ background: transparent; color: {error}; font-weight: 700; }}
QLabel#start_banner_hint {{ background: transparent; color: {body}; }}
QFrame#doc_panel QLabel#lang_notice, QLabel#lang_notice {{ background: {warn-bg}; color: {warn}; font-size: 12px; border: none; border-radius: 0; padding: 6px 10px; min-height: 18px; }}   /* 시각 설계 7-12 설정의 언어 절: 경고 상태 줄, 높이 30 */
QLabel#lang_row_label {{ color: {body}; background: transparent; }}
QFrame#win_bottom {{ background: {canvas}; border: none; border-top: 1px solid {hairline}; }}
QLineEdit#path_edit {{ font-family: Menlo, monospace; font-size: 12pt; }}
QLineEdit[valuebox="true"] {{ background: {value-box}; color: {ink}; border: none; border-radius: 8px; padding: 0 12px; }}
QLineEdit[keywarn="true"], QLineEdit[keywarn="true"]:focus {{ border: 1px solid {warn}; }}      /* 경고색이 포커스 테두리보다 앞선다(시각 설계 7-12) */
QLabel#key_label {{ background: transparent; color: {ink}; font-size: 13px; font-weight: 500; }}
QPlainTextEdit#session_prompt {{ background: {surface-elevated}; color: {ink}; border: 1px solid {hairline}; border-radius: 10px; padding: 10px 12px; }}
QFrame#materials_table {{ background: {surface}; border: 1px solid {hairline}; border-radius: 10px; }}
QFrame#materials_head {{ background: {surface-elevated}; border: none; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
QLabel#materials_head_cell {{ background: transparent; color: {mute}; font-size: 12px; }}
QScrollArea#materials_rows, QWidget#materials_rows_host {{ background: {surface}; border: none; }}
QFrame#materials_row {{ background: {surface}; border: none; border-top: 1px solid {hairline}; }}
QLabel#materials_cell {{ background: transparent; color: {ink}; }}
QPushButton#materials_remove {{ background: transparent; color: {mute}; border: none; font-size: 12px; padding: 0; min-height: 0; }}
QPushButton#materials_remove:hover {{ color: {ink}; }}
QPushButton#materials_remove:disabled {{ color: {mute}; }}
QLabel#materials_footer {{ background: {surface}; color: {mute}; font-size: 12px; border: none; border-top: 1px solid {hairline}; padding: 0 14px; }}
QLabel#materials_empty {{ background: transparent; color: {mute}; font-size: 12pt; }}
QScrollArea#start_scroll {{ background: {canvas}; border: none; }}
QWidget#start_body {{ background: {canvas}; }}
QScrollBar:vertical {{ background: {sb-track}; width: 12px; margin: 0; border: none; }}
QScrollBar:horizontal {{ background: {sb-track}; height: 12px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: {sb-thumb}; min-height: 24px; margin: 2px; border-radius: 4px; }}
QScrollBar::handle:horizontal {{ background: {sb-thumb}; min-width: 24px; margin: 2px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {sb-hover}; }}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{ background: {sb-press}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; background: none; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{ background: {surface-card}; color: {ink}; border: 1px solid {hairline}; padding: 4px 8px; }}
"""


def tokens(scheme: str) -> dict:
    return dict(TOKENS["dark" if scheme == "dark" else "light"])


def stylesheet(scheme: str) -> str:
    """`scheme`: `light` · `dark`. 알 수 없는 값은 밝게 본다."""
    return _TEMPLATE.format(**tokens(scheme))
