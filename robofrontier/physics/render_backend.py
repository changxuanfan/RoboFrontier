"""Record the actual observation renderer and reject a silent backend change."""


def validate_backend(requested, vendor, renderer, version):
    vendor, renderer, version = (value.decode(errors='replace') if isinstance(value, bytes) else str(value or '')
                                 for value in (vendor, renderer, version))
    if not vendor or not renderer:
        raise RuntimeError('OpenGL did not report its observation renderer')
    if requested == 'nvidia' and 'nvidia' not in (vendor+' '+renderer).lower():
        raise RuntimeError('NVIDIA rendering was requested but the active OpenGL renderer is '+vendor+' / '+renderer)
    if requested == 'cpu' and not any(name in renderer.lower() for name in ('llvmpipe', 'softpipe', 'software')):
        raise RuntimeError('CPU rendering was requested but the active OpenGL renderer is '+vendor+' / '+renderer)
    if requested not in (None, 'nvidia', 'cpu', 'native'):
        raise ValueError('Unknown frozen rendering device')
    return {'requested_device': requested, 'gl_vendor': vendor, 'gl_renderer': renderer,
            'gl_version': version, 'scope': 'Observation context; MuJoCo dynamics execute on CPU'}


def current_backend(requested=None):
    # Import only after the selected context is current and its environment has
    # been set. Importing OpenGL before selecting EGL/OSMesa can bind the wrong ABI.
    from OpenGL import GL
    return validate_backend(requested, GL.glGetString(GL.GL_VENDOR),
                            GL.glGetString(GL.GL_RENDERER), GL.glGetString(GL.GL_VERSION))
