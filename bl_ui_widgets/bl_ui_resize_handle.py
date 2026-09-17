from .bl_ui_widget import BL_UI_Widget


class BL_UI_Resize_Handle(BL_UI_Widget):
    """Thin single-axis drag handle for resizing a panel along its bottom edge.

    Self-contained: it rides on the framework's existing event dispatch
    (``handle_event`` -> ``mouse_down``/``mouse_move``/``mouse_up``) and hover
    callbacks (``set_mouse_enter``/``set_mouse_exit``). It does not paint while
    idle - only while an active drag is in progress, to give the user visual
    feedback before the row count actually changes.

    Callbacks (each receives the handle as first arg):
      * ``on_drag_begin(handle, start_y)``  - threshold crossed, drag started
      * ``on_drag_update(handle, y)``       - pointer moved during drag
      * ``on_drag_end(handle, y, hovering=bool)`` - drag released
      * ``on_click(handle)``                - pressed and released without drag
    """

    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        self.dragging = False
        self.press_active = False
        self.start_y = 0
        self.threshold_px = 0
        self.on_drag_begin = None
        self.on_drag_update = None
        self.on_drag_end = None
        self.on_click = None

    def _call(self, callback, *args, **kwargs):
        if callable(callback):
            callback(self, *args, **kwargs)

    def _threshold_reached(self, y):
        return abs(y - self.start_y) >= self.threshold_px

    def mouse_down(self, x, y):
        if not self.is_in_rect(x, y):
            return False
        self.press_active = True
        self.start_y = y
        return True

    def mouse_move(self, x, y):
        if not self.press_active:
            return
        if not self.dragging:
            if not self._threshold_reached(y):
                return
            self.dragging = True
            self._call(self.on_drag_begin, self.start_y)
            self._call(self.on_drag_update, y)
            return
        self._call(self.on_drag_update, y)

    def mouse_up(self, x, y):
        if not self.press_active:
            return
        if self.dragging:
            self._call(self.on_drag_end, y, hovering=self.is_in_rect(x, y))
        elif self.is_in_rect(x, y):
            self._call(self.on_click)
        self.press_active = False
        self.dragging = False

    def draw(self):
        # Paint the line only during an active drag; idle feedback is the
        # hover cursor set by the owner via set_mouse_enter/set_mouse_exit.
        if not self._is_visible or not self.dragging:
            return
        self.shader.bind()
        self.shader.uniform_float("color", self._bg_color)
        self._draw_panel_batch()
