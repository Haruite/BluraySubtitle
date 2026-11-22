"""Report the active GTK desktop colors without loading host GTK into bundled Qt."""

import ctypes as c
from ctypes.util import find_library
import json
import os
import sys


def function(library, name, result, *arguments):
    fn = getattr(library, name)
    fn.restype = result
    fn.argtypes = list(arguments)
    return fn


def library(name, soname):
    return c.CDLL(find_library(name) or soname)


def main():
    ptr, integer, string = c.c_void_p, c.c_int, c.c_char_p
    gobject = library("gobject-2.0", "libgobject-2.0.so.0")
    glib = library("glib-2.0", "libglib-2.0.so.0")
    modern = sys.argv[1:] == ["gnome"]
    if modern:
        try:
            adw = library("adwaita-1", "libadwaita-1.so.0")
            get_accent = function(adw, "adw_style_manager_get_accent_color_rgba", ptr, ptr)
        except (AttributeError, OSError):
            # GTK 3 and GTK 4 cannot share a process.
            os.execv(sys.executable, [sys.executable, "-I", "-B", __file__, "gtk3"])
        gtk = library("gtk-4", "libgtk-4.so.1")
        if not function(gtk, "gtk_init_check", integer)():
            return
        function(adw, "adw_init", None)()
        manager = function(adw, "adw_style_manager_get_default", ptr)()
        rgba_free = function(gtk, "gdk_rgba_free", None, ptr)
    else:
        gtk = library("gtk-3", "libgtk-3.so.0")
        if not function(gtk, "gtk_init_check", integer, ptr, ptr)(None, None):
            return
        widget = function(gtk, "gtk_tree_view_new", ptr)()
        function(gobject, "g_object_ref_sink", ptr, ptr)(widget)
        context = function(gtk, "gtk_widget_get_style_context", ptr, ptr)(widget)
        lookup = function(gtk, "gtk_style_context_lookup_color", integer, ptr, string, ptr)
    settings = function(gtk, "gtk_settings_get_default", ptr)()
    get_property = function(gobject, "g_object_get", None, ptr, string)
    idle_add = function(glib, "g_idle_add", c.c_uint, ptr, ptr)
    loop = function(glib, "g_main_loop_new", ptr, ptr, integer)(None, False)
    quit_loop = function(glib, "g_main_loop_quit", None, ptr)
    pending = False
    last = None

    @c.CFUNCTYPE(integer, ptr)
    def publish(_):
        nonlocal pending, last
        pending = False
        color = None
        if modern:
            rgba = get_accent(manager)
            if rgba:
                color = list(c.cast(rgba, c.POINTER(c.c_float * 4)).contents[:3])
                rgba_free(rgba)
        else:
            rgba = (c.c_double * 4)()
            for name in (b"theme_selected_bg_color", b"accent_bg_color", b"selected_bg_color"):
                if lookup(context, name, c.byref(rgba)) and rgba[3] > 0:
                    color = list(rgba[:3])
                    break
        animated = integer()
        get_property(settings, b"gtk-enable-animations", c.byref(animated), ptr())
        state = (color, not bool(animated.value))
        if state != last:
            print(json.dumps(state), flush=True)
            last = state
        return False

    @c.CFUNCTYPE(None, ptr, ptr, ptr)
    def changed(*_):
        nonlocal pending
        if not pending:
            pending = True
            idle_add(publish, None)

    @c.CFUNCTYPE(None, ptr, ptr)
    def style_changed(_context, _data):
        changed(None, None, None)

    @c.CFUNCTYPE(integer, integer, integer, ptr)
    def detached(*_):
        quit_loop(loop)
        return False

    connect = function(gobject, "g_signal_connect_data", c.c_ulong, ptr, string, ptr, ptr, ptr, integer)
    for signal in (b"notify::gtk-enable-animations", b"notify::gtk-theme-name"):
        connect(settings, signal, changed, None, None, 0)
    if modern:
        connect(manager, b"notify::accent-color-rgba", changed, None, None, 0)
    else:
        connect(settings, b"notify::gtk-color-scheme", changed, None, None, 0)
        connect(context, b"changed", style_changed, None, None, 0)
    # The parent's stdin pipe closes even if the GUI exits unexpectedly.
    function(glib, "g_unix_fd_add", c.c_uint, integer, integer, ptr, ptr)(0, 16 | 8, detached, None)
    publish(None)
    function(glib, "g_main_loop_run", None, ptr)(loop)


if __name__ == "__main__":
    try:
        main()
    except (OSError, AttributeError):
        # GTK is optional on freedesktop systems using another toolkit.
        pass
