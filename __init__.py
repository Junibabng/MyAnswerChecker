import logging
import os
import sys
from aqt import mw, gui_hooks
from aqt.qt import QAction, QMenu
from aqt.gui_hooks import reviewer_did_show_question, reviewer_did_show_answer
from aqt.utils import showWarning, showInfo
from anki.cards import Card
from typing import Optional, Any

# Ensure vendored dependencies in libs/ are importable
try:
    _libs_path = os.path.join(__path__[0], "libs")  # type: ignore[name-defined]
    if os.path.isdir(_libs_path) and _libs_path not in sys.path:
        sys.path.insert(0, _libs_path)
except Exception:
    # Best-effort; avoid breaking addon load on failure
    pass

from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow
from .main import add_menu, openSettingsDialog, initialize_addon, load_global_settings
from .settings_manager import settings_manager
from .auto_difficulty import extract_difficulty

# Global instances
bridge: Optional[Bridge] = None
answer_checker_window: Optional[AnswerCheckerWindow] = None

# Setup logging
logger = logging.getLogger(__name__)

def initialize_addon() -> None:
    """Initialize the addon when profile is loaded"""
    global bridge
    try:
        if bridge is None:
            bridge = Bridge()
            load_global_settings()
            register_hooks()
            add_menu()
            logger.info("Addon initialized successfully with JSON buffering")
    except Exception as e:
        logger.error(f"Error initializing addon: {str(e)}")
        showWarning(f"Error initializing addon: {str(e)}")

def register_hooks() -> None:
    """Register all necessary hooks"""
    for hook, callback in [
        (reviewer_did_show_question, show_question_),
        (reviewer_did_show_answer, show_answer_)
    ]:
        hook.append(callback)
        logger.debug("Registered hook")

def show_question_(card: Card) -> None:
    """카드 질문이 표시될 때 호출되는 핸들러"""
    if bridge:
        bridge.start_timer()

def show_answer_(card: Card) -> None:
    """카드 답변이 표시될 때 호출되는 핸들러"""
    if bridge:
        bridge.stop_timer()

def show_answer_checker() -> None:
    """답변 체크 창을 표시합니다."""
    global bridge, answer_checker_window
    
    if answer_checker_window is None:
        if bridge is None:
            bridge = Bridge()
        answer_checker_window = AnswerCheckerWindow(bridge)
        bridge.set_answer_checker_window(answer_checker_window)
    
    answer_checker_window.show()
    answer_checker_window.activateWindow()

def on_profile_loaded() -> None:
    """Function to be executed when the profile is loaded"""
    global bridge
    try:
        if bridge is None:
            initialize_addon()
            logger.info("Addon initialization complete")
        else:
            logger.info("Addon already initialized.")
    except Exception as e:
        logger.exception("Error initializing addon: %s", e)
        showInfo(f"Error initializing addon: {str(e)}")

# Register the profile loaded hook
gui_hooks.profile_did_open.append(on_profile_loaded)

# Register reviewer hooks
gui_hooks.reviewer_did_show_question.append(show_question_)
gui_hooks.reviewer_did_show_answer.append(show_answer_)