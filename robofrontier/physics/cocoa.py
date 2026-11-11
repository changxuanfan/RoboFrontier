"""Start GLFW on macOS without waiting on window restoration.

When a Python process that opened a window has quit unexpectedly, macOS asks at the next
GLFW start whether to reopen its windows, in a modal dialog that a world started by a service
never shows and nobody answers, so `glfw.init()` waits forever. Registering
ApplePersistenceIgnoreState for this process only (the registration domain, nothing saved)
skips restoration; no window is ever restored in a world.
"""
import ctypes
import ctypes.util
import sys


def ignore_saved_windows():
    if sys.platform != 'darwin':
        return
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
    ctypes.cdll.LoadLibrary('/System/Library/Frameworks/Foundation.framework/Foundation')
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def call(target, name, *args, types=()):
        send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *types)(('objc_msgSend', objc))
        return send(target, objc.sel_registerName(name.encode()), *args)

    def cls(name):
        return objc.objc_getClass(name.encode())

    key = call(cls('NSString'), 'stringWithUTF8String:', b'ApplePersistenceIgnoreState', types=(ctypes.c_char_p,))
    yes = call(cls('NSNumber'), 'numberWithBool:', True, types=(ctypes.c_bool,))
    table = call(cls('NSDictionary'), 'dictionaryWithObject:forKey:', yes, key, types=(ctypes.c_void_p, ctypes.c_void_p))
    call(call(cls('NSUserDefaults'), 'standardUserDefaults'), 'registerDefaults:', table, types=(ctypes.c_void_p,))


def start_glfw():
    """Import and initialize GLFW; raises when it cannot start."""
    ignore_saved_windows()
    import glfw
    if not glfw.init():
        raise RuntimeError('GLFW init failed')
    return glfw
