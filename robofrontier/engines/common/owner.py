"""The environment of a run's physics process (the owner), the same for every engine.

The owner gets only what it needs to simulate and render: no model credentials, no
provider settings. Thread counts are fixed so that many parallel runs do not each start a
thread per core: numerical libraries use one thread, and the CPU renderer (llvmpipe, used
where there is no GPU) two. The owner runs in its own process group.

    python -m robofrontier.engines.common.owner env   # the owner environment, as JSON
"""
import json
import os
import sys

PASSED = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'DISPLAY', 'MUJOCO_GL', 'PYOPENGL_PLATFORM',
          'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'CUDA_VISIBLE_DEVICES', 'MUJOCO_EGL_DEVICE_ID',
          'PYTHONPATH', 'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH',
          # What doctor's render probe passes, so a world renders where doctor said it would.
          'NVIDIA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES', '__EGL_VENDOR_LIBRARY_FILENAMES')
THREADS = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'LP_NUM_THREADS': '2'}


def environment(base=None):
    """The owner's environment from the host's: the allowlisted names and the fixed threads."""
    base = os.environ if base is None else base
    return {**{k: base[k] for k in PASSED if k in base}, **THREADS}


def command(run, python=None):
    return [python or sys.executable, '-m', 'robofrontier.runtime.pipeline', '--run-dir', str(run), '--hidden']


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ['env']: raise SystemExit('usage: python -m robofrontier.engines.common.owner env')
    print(json.dumps(environment()))


if __name__ == '__main__':
    main()
