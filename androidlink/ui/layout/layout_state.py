"""Panel layout persistence (prompt.md section 16) is implemented directly
in ui/windows/main_window.py: panels are QDockWidgets, and
QMainWindow.saveState()/restoreState() (base64-encoded into
settings.general.layout_state) handles show/hide, rearrange, float, and
resize. This module is kept as a placeholder in case layout logic grows
complex enough to warrant splitting out of main_window.py.
"""
