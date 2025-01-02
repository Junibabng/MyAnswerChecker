from aqt import mw, gui_hooks
from aqt.qt import QAction, QMenu
from aqt.gui_hooks import reviewer_did_show_question, reviewer_did_show_answer
from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow
from .main import openSettingsDialog, load_global_settings

# Global bridge instance
bridge = None
answer_checker_window = None

def initialize_addon():
    """Initialize the addon when profile is loaded"""
    global bridge
    try:
        if bridge is None:
            bridge = Bridge()
            load_global_settings()
            register_hooks()
            add_menu()
    except Exception as e:
        from aqt.utils import showWarning
        showWarning(f"Error initializing addon: {str(e)}")

def register_hooks():
    """Register all necessary hooks"""
    reviewer_did_show_question.append(on_show_question)
    reviewer_did_show_answer.append(on_show_answer)

def on_show_question(card):
    """Hook for when a question is shown"""
    global bridge
    if bridge:
        bridge.start_timer()

def on_show_answer(card):
    """Hook for when an answer is shown"""
    global bridge
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
        from aqt.utils import showWarning
        showWarning(f"Error opening Answer Checker: {str(e)}")

def add_menu():
    menubar = mw.form.menubar
    tools_menu = None
    for action in menubar.actions():
        if action.text() == "&Tools":
            tools_menu = action.menu()
            break
    if not tools_menu:
        return

    answer_checker_menu = QMenu("Answer Checker", tools_menu)
    tools_menu.addMenu(answer_checker_menu)

    open_action = QAction("Open Answer Checker", answer_checker_menu)
    open_action.triggered.connect(open_answer_checker_window)
    answer_checker_menu.addAction(open_action)

    settings_action = QAction("Settings", answer_checker_menu)
    settings_action.triggered.connect(openSettingsDialog)
    answer_checker_menu.addAction(settings_action)

# Initialize addon when profile is loaded
gui_hooks.profile_did_open.append(initialize_addon)