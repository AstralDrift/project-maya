"""setup.has_vram_bar: a discrete GPU without Resizable BAR (256 MB window) is not unified memory."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import setup  # noqa: E402

MB = 1 << 20


class HasVramBar(unittest.TestCase):
    def test_rtx4090_rebar_off(self):          # measured: /sys/bus/pci/devices/0000:01:00.0/resource
        self.assertTrue(setup.has_vram_bar([16 * MB, 256 * MB, 32 * MB]))

    def test_rebar_on(self):
        self.assertTrue(setup.has_vram_bar([16 * MB, 32 << 30, 32 * MB]))

    def test_register_window_only(self):       # unified-memory parts: no VRAM aperture
        self.assertFalse(setup.has_vram_bar([16 * MB, 32 * MB]))


if __name__ == "__main__":
    unittest.main()
