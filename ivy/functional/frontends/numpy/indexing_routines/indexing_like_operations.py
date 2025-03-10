import ivy
from ivy.functional.frontends.numpy.func_wrapper import (
    to_ivy_arrays_and_back,
    outputs_to_numpy_arrays,
)


@to_ivy_arrays_and_back
def diagonal(a, offset, axis1, axis2):
    return ivy.diagonal(a, offset=offset, axis1=axis1, axis2=axis2)


@outputs_to_numpy_arrays
def diag_indices(n, ndim=2):
    idx = ivy.arange(n, dtype=int)
    return (idx,) * ndim


@to_ivy_arrays_and_back
def diag(v, k=0):
    return ivy.diag(v, k=k)


@to_ivy_arrays_and_back
def take_along_axis(arr, indices, axis):
    return ivy.take_along_axis(arr, indices, axis)


@to_ivy_arrays_and_back
def tril_indices(n, k=0, m=None):
    return ivy.tril_indices(n, m, k)


@to_ivy_arrays_and_back
def indices(dimensions, dtype=int, sparse=False):
    dimensions = tuple(dimensions)
    N = len(dimensions)
    shape = (1,) * N
    if sparse:
        res = tuple()
    else:
        res = ivy.empty((N,) + dimensions, dtype=dtype)
    for i, dim in enumerate(dimensions):
        idx = ivy.arange(dim, dtype=dtype).reshape(
            shape[:i] + (dim,) + shape[i + 1:]
        )
        if sparse:
            res = res + (idx,)
        else:
            res[i] = idx
    return res
