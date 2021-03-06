import torch
from tests.common import TestCase

from dsntnn import make_gauss


class TestMakeGauss(TestCase):
    def test_2d(self):
        expected = torch.Tensor([
            [0.002969, 0.013306, 0.021938, 0.013306, 0.002969],
            [0.013306, 0.059634, 0.098320, 0.059634, 0.013306],
            [0.021938, 0.098320, 0.162103, 0.098320, 0.021938],
            [0.013306, 0.059634, 0.098320, 0.059634, 0.013306],
            [0.002969, 0.013306, 0.021938, 0.013306, 0.002969],
        ])
        actual = make_gauss(torch.Tensor([0, 0]), [5, 5], sigma=1.0)
        self.assertEqual(expected, actual, 1e-5)

    def test_3d(self):
        expected = torch.Tensor([[
            [0.000035, 0.000002, 0.000000],
            [0.009165, 0.000570, 0.000002],
            [0.147403, 0.009165, 0.000035],
        ], [
            [0.000142, 0.000009, 0.000000],
            [0.036755, 0.002285, 0.000009],
            [0.591145, 0.036755, 0.000142],
        ], [
            [0.000035, 0.000002, 0.000000],
            [0.009165, 0.000570, 0.000002],
            [0.147403, 0.009165, 0.000035],
        ]])
        actual = make_gauss(torch.Tensor([-1, 1, 0]), [3, 3, 3], sigma=0.6)
        self.assertEqual(expected, actual, 1e-5)

    def test_unnormalized(self):
        actual = make_gauss(torch.Tensor([0, 0]), [5, 5], sigma=1.0, normalize=False)
        self.assertEqual(1.0, actual.max())

    def test_rectangular(self):
        expected = torch.Tensor([
            [0.496683, 0.182719, 0.024728, 0.001231, 0.000023],
            [0.182719, 0.067219, 0.009097, 0.000453, 0.000008],
            [0.024728, 0.009097, 0.001231, 0.000061, 0.000001],
        ])
        actual = make_gauss(torch.Tensor([-1, -1]), [3, 5], sigma=1.0)
        self.assertEqual(expected, actual, 1e-5)
