# Copyright 2017 Aiden Nibali
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Differentiable DSNT operations for use in PyTorch computation graphs.
"""

from functools import reduce
from operator import mul

import torch
import torch.nn.functional
from torch.autograd import Variable


def _type_as(tensor, other, requires_grad=False):
    """Type a tensor to match the type of another object.

    If `other` is a Variable, `tensor` will be wrapped in a Variable also.
    """
    if isinstance(other, Variable):
        tensor = Variable(tensor, requires_grad=requires_grad)
    return tensor.type_as(other)


def _normalized_linspace(length, type_as):
    """Generate a vector with values ranging from -1 to 1.

    Note that the values correspond to the "centre" of each cell, so
    -1 and 1 are always conceptually outside the bounds of the vector.
    For example, if length = 4, the following vector is generated:

    ```text
     [ -0.75, -0.25,  0.25,  0.75 ]
     ^              ^             ^
    -1              0             1
    ```

    Args:
        length: The length of the vector
        type_as: An object to type the vector as

    Returns:
        The generated vector
    """
    first = -(length - 1) / length
    last = (length - 1) / length
    vec = torch.linspace(first, last, length)
    return _type_as(vec, type_as)


def _coord_expectation(heatmaps, dim, ndims, transform=None):
    """Calculate the coordinate expected value along an axis.

    Args:
        heatmaps: Normalized heatmaps (probabilities)
        dim: Dimension of the coordinate axis
        transform: Coordinate transformation function, defaults to identity

    Returns:
        The coordinate expected value, `E[transform(X)]`
    """
    dim_size = heatmaps.size()[dim]
    own_coords = _normalized_linspace(dim_size, type_as=heatmaps)
    if transform:
        own_coords = transform(own_coords)
    first_dims = heatmaps.size()[:-ndims]
    hm_dims = heatmaps.size()[-ndims:]
    summed = heatmaps.view(-1, *hm_dims)
    for i in range(-ndims, 0):
        if i != dim:
            summed = summed.sum(i, keepdim=True)
    summed = summed.view(summed.size(0), -1)
    expectations = summed.mul(own_coords.view(-1, own_coords.size(-1))).sum(-1, keepdim=False)
    if len(first_dims) > 0:
        expectations = expectations.view(*first_dims)
    return expectations


def _coord_variance(heatmaps, dim, ndims):
    """Calculate the coordinate variance along an axis.

    Args:
        heatmaps: Normalized heatmaps (probabilities)
        dim: Dimension of the coordinate axis

    Returns:
        The coordinate variance, `Var[X] =  E[(X - E[x])^2]`
    """
    # mu_x = E[X]
    mu_x = _coord_expectation(heatmaps, dim, ndims)
    # var_x = E[(X - mu_x)^2]
    var_x = _coord_expectation(heatmaps, dim, ndims, lambda x: (x - mu_x) ** 2)
    return var_x


def dsnt(heatmaps, ndims=2):
    """Differentiable spatial to numerical transform.

    Args:
        heatmaps (torch.Tensor): Spatial representation of locations
        ndims (int): the number of dimensions in a heatmap

    Returns:
        Numerical coordinates corresponding to the locations in the heatmaps.
    """

    dim_range = range(-1, -(ndims + 1), -1)
    mu = torch.stack([_coord_expectation(heatmaps, dim, ndims) for dim in dim_range], -1)
    return mu


def average_loss(losses, mask=None):
    """Calculate the average of per-location losses.

    Args:
        losses (Tensor): Predictions ([batches x] n)
        mask (Tensor, optional): Mask of points to include in the loss calculation
            ([batches x] n), defaults to including everything
    """

    if mask is not None:
        losses = losses * mask
        denom = mask.sum()
    else:
        denom = losses.numel()

    # Prevent division by zero
    if isinstance(denom, int):
        denom = max(denom, 1)
    else:
        denom = denom.clamp(1)

    return losses.sum() / denom


def flat_softmax(inp, ndims=2):
    """Compute the softmax with the last `ndims` tensor dimensions combined."""
    orig_size = inp.size()
    flat = inp.view(-1, reduce(mul, orig_size[-ndims:]))
    flat = torch.nn.functional.softmax(flat)
    return flat.view(*orig_size)


def euclidean_losses(actual, target):
    """Calculate the average Euclidean loss for multi-point samples.

    Each sample must contain `n` points, each with `d` dimensions. For example,
    in the MPII human pose estimation task n=16 (16 joint locations) and
    d=2 (locations are 2D).

    Args:
        actual (Tensor): Predictions ([batches x] n x d)
        target (Tensor): Ground truth target ([batches x] n x d)
    """

    # Calculate Euclidean distances between actual and target locations
    diff = actual - target
    dist_sq = diff.pow(2).sum(-1, keepdim=False)
    dist = dist_sq.sqrt()
    return dist


def make_gauss(means, size, sigma, normalize=True):
    """Draw Gaussians.

    This function is differential with respect to means.

    Note on ordering: `size` expects [..., depth, height, width], whereas
    `means` expects x, y, z, ...

    Args:
        means: coordinates containing the Gaussian means (units: normalized coordinates)
        size: size of the generated images (units: pixels)
        sigma: standard deviation of the Gaussian (units: pixels)
        normalize: when set to True, the returned Gaussians will be normalized
    """

    dim_range = range(-1, -(len(size) + 1), -1)
    coords_list = [_normalized_linspace(s, type_as=means) for s in reversed(size)]

    # PDF = exp(-(x - \mu)^2 / (2 \sigma^2))

    # dists <- (x - \mu)^2
    dists = [(x - mean) ** 2 for x, mean in zip(coords_list, means.split(1, -1))]

    # ks <- -1 / (2 \sigma^2)
    stddevs = [2 * sigma / s for s in reversed(size)]
    ks = [-0.5 * (1 / stddev) ** 2 for stddev in stddevs]

    exps = [(dist * k).exp() for k, dist in zip(ks, dists)]

    # Combine dimensions of the Gaussian
    gauss = reduce(mul, [
        reduce(lambda t, d: t.unsqueeze(d), filter(lambda d: d != dim, dim_range), dist)
        for dim, dist in zip(dim_range, exps)
    ])

    if not normalize:
        return gauss

    # Normalize the Gaussians
    val_sum = reduce(lambda t, dim: t.sum(dim, keepdim=True), dim_range, gauss) + 1e-24
    return gauss / val_sum


def _kl(p, q, ndims, eps=1e-24):
    unsummed_kl = p * ((p + eps).log() - (q + eps).log())
    kl_values = reduce(lambda t, _: t.sum(-1, keepdim=False), range(ndims), unsummed_kl)
    return kl_values


def _js(p, q, ndims, eps=1e-24):
    m = 0.5 * (p + q)
    return 0.5 * _kl(p, m, ndims, eps) + 0.5 * _kl(q, m, ndims, eps)


def kl_reg_losses(heatmaps, mu_t, sigma_t):
    """Calculate Kullback-Leibler divergences between heatmaps and target Gaussians.

    Args:
        heatmaps (torch.Tensor): Heatmaps generated by the model
        mu_t (torch.Tensor): Centers of the target Gaussians (in normalized units)
        sigma_t (float): Standard deviation of the target Gaussians (in pixels)

    Returns:
        Per-location KL divergences.
    """

    ndims = mu_t.size(-1)
    gauss = make_gauss(mu_t, heatmaps.size()[-ndims:], sigma_t)
    divergences = _kl(heatmaps, gauss, ndims)
    return divergences


def js_reg_losses(heatmaps, mu_t, sigma_t):
    """Calculate Jensen-Shannon divergences between heatmaps and target Gaussians.

    Args:
        heatmaps (torch.Tensor): Heatmaps generated by the model
        mu_t (torch.Tensor): Centers of the target Gaussians (in normalized units)
        sigma_t (float): Standard deviation of the target Gaussians (in pixels)

    Returns:
        Per-location JS divergences.
    """

    ndims = mu_t.size(-1)
    gauss = make_gauss(mu_t, heatmaps.size()[-ndims:], sigma_t)
    divergences = _js(heatmaps, gauss, ndims)
    return divergences


def variance_reg_losses(heatmaps, sigma_t, ndims=2):
    """Calculate the loss between heatmap variances and target variance.

    Note that this is slightly different from the version used in the
    DSNT paper. This version uses pixel units for variance, which
    produces losses that are larger by a constant factor.

    Args:
        heatmaps (torch.Tensor): Heatmaps generated by the model
        sigma_t (float): Target standard deviation (in pixels)
        ndims (int): Number of dimensions in a heatmap

    Returns:
        Per-location sum of square errors for variance.
    """

    variance = torch.stack([_coord_variance(heatmaps, d, ndims) for d in range(-ndims, 0)], -1)
    heatmap_size = _type_as(torch.Tensor(list(heatmaps.size()[-ndims:])), variance)
    actual_variance = variance * (heatmap_size / 2) ** 2
    target_variance = sigma_t ** 2
    diff = (actual_variance - target_variance)
    sq_error = diff ** 2

    return sq_error.sum(-1, keepdim=False)
