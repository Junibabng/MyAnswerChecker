import logging
from aqt import mw, gui_hooks
from aqt.qt import QAction, QMenu
from aqt.gui_hooks import reviewer_did_show_question, reviewer_did_show_answer
from aqt.utils import showWarning, showInfo
from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow
from .main import add_menu, openSettingsDialog, initialize_addon, load_global_settings
from .settings_manager import settings_manager

# Global instances
bridge = None
answer_checker_window = None

# Setup logging
logger = logging.getLogger(__name__)

def initialize_addon():
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

def register_hooks():
    """Register all necessary hooks"""
    for hook, callback in [
        (reviewer_did_show_question, on_show_question),
        (reviewer_did_show_answer, on_show_answer)
    ]:
        hook.append(callback)
        logger.debug("Registered hook")

def on_show_question(card):
    """Hook for when a question is shown"""
    if bridge:
        bridge.start_timer()

def on_show_answer(card):
    """Hook for when an answer is shown"""
    if bridge:
        bridge.stop_timer()

def open_answer_checker_window():
    """Opens the answer checker window"""
    global answer_checker_window, bridge
    try:
        if not bridge:
            initialize_addon()
        answer_checker_window = AnswerCheckerWindow(bridge, mw)
        answer_checker_window.show()
    except Exception as e:
        logger.error(f"Error opening Answer Checker: {str(e)}")
        showWarning(f"Error opening Answer Checker: {str(e)}")

def on_profile_loaded():
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
gui_hooks.reviewer_did_show_question.append(on_show_question)
gui_hooks.reviewer_did_show_answer.append(on_show_answer)