import unittest

from robofrontier.physics.render_backend import validate_backend


class RenderBackendTests(unittest.TestCase):
    def test_selected_nvidia_cannot_silently_become_mesa_software(self):
        with self.assertRaisesRegex(RuntimeError,'NVIDIA rendering was requested'):
            validate_backend('nvidia',b'Mesa',b'llvmpipe',b'4.5')
        report=validate_backend('nvidia',b'NVIDIA Corporation',b'NVIDIA H800',b'4.6')
        self.assertEqual(report['gl_vendor'],'NVIDIA Corporation')

    def test_cpu_and_native_are_distinct_without_changing_legacy_contexts(self):
        self.assertEqual(validate_backend('cpu','Mesa','llvmpipe (LLVM)','4.5')['requested_device'],'cpu')
        with self.assertRaisesRegex(RuntimeError,'CPU rendering was requested'):
            validate_backend('cpu','Apple','Apple M5','4.1')
        self.assertEqual(validate_backend('native','Apple','Apple M5','4.1')['gl_renderer'],'Apple M5')
        self.assertIsNone(validate_backend(None,'Mesa','llvmpipe','4.5')['requested_device'])


if __name__=='__main__':unittest.main()
