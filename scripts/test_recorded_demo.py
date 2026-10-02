import tempfile
import unittest
from pathlib import Path
import numpy as np
from prepare_recorded_demo import canonical_cloud, prepare, read_cloud


class RecordedDemoTests(unittest.TestCase):
    def test_canonical_order_and_colors(self):
        xyz = np.array([[1., 0, 0], [0, 0, 0], [.01, 0, 0]])
        rgb = np.array([[255, 0, 0], [0, 100, 0], [0, 200, 0]])
        a = canonical_cloud(xyz, rgb, .03)
        b = canonical_cloud(xyz[::-1], rgb[::-1], .03)
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], [[0, 150, 0], [255, 0, 0]])
        self.assertEqual(a[2], b[2])

    def test_voxel_changes_fingerprint(self):
        xyz = np.array([[0., 0, 0]])
        rgb = np.array([[0, 0, 0]])
        self.assertNotEqual(canonical_cloud(xyz, rgb, .03)[2], canonical_cloud(xyz, rgb, .04)[2])

    def test_empty_and_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):
            canonical_cloud(np.array([[np.nan, 0, 0]]), np.zeros((1, 3)), .03)
        with self.assertRaises(ValueError):
            canonical_cloud(np.zeros((1, 3)), np.zeros((1, 3)), 0)

    def test_source_cannot_be_output(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                prepare(Path(folder), Path(folder) / 'out')

    def test_unsupported_ply_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.ply'
            path.write_bytes(b'ply\nformat ascii 1.0\n')
            with self.assertRaises(ValueError):
                read_cloud(path)


if __name__ == '__main__':
    unittest.main()
