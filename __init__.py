import logging
from aqt import mw, gui_hooks
from aqt.qt import QAction, QMenu
from aqt.gui_hooks import reviewer_did_show_question, reviewer_did_show_answer
from aqt.utils import showWarning
from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow
from .main import openSettingsDialog, load_global_settings

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

def add_menu():
    """Add menu items to Anki"""
    try:
        tools_menu = next((action.menu() for action in mw.form.menubar.actions() 
                          if action.text() == "&Tools"), None)
        if not tools_menu:
            logger.error("Tools menu not found")
            return

        answer_checker_menu = QMenu("Answer Checker", tools_menu)
        tools_menu.addMenu(answer_checker_menu)

        menu_items = [
            ("Open Answer Checker", open_answer_checker_window),
            ("Settings", openSettingsDialog)
        ]

        for label, callback in menu_items:
            action = QAction(label, answer_checker_menu)
            action.triggered.connect(callback)
            answer_checker_menu.addAction(action)
            
        logger.debug("Menu items added successfully")
    except Exception as e:
        logger.error(f"Error adding menu items: {str(e)}")

# Initialize addon when profile is loaded
gui_hooks.profile_did_open.append(initialize_addon)