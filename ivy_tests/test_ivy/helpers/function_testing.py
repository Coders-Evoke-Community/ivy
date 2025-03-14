# global
# flake8: noqa
import os
import copy
from typing import Union, List
import numpy as np
import types
import importlib
import inspect

try:
    import jsonpickle
except:
    pass


def framework_comparator(frontend):
    if ivy.current_backend_str() != frontend.split("/")[0]:
        return False
    if frontend.split("/")[0] == "jax":
        fw = frontend.split("/")[1] + frontend.split("/")[3]
        backend_fw = (
            importlib.import_module("jax").__version__
            + importlib.import_module("jaxlib").__version__
        )
        return backend_fw == fw
    elif frontend.split("/")[0] == "torch":
        return (
            frontend.split("/")[1]
            == importlib.import_module(frontend.split("/")[1]).__version__.split("+")[0]
        )
    else:
        return (
            frontend.split("/")[0]
            == importlib.import_module(frontend.split("/")[0]).__version__
        )


try:
    import tensorflow as tf
except ImportError:
    tf = types.SimpleNamespace()
    tf.TensorShape = None

# local
import ivy
from ivy_tests.test_ivy.helpers.test_parameter_flags import FunctionTestFlags
import ivy_tests.test_ivy.helpers.test_parameter_flags as pf
from ivy_tests.test_ivy.helpers.available_frameworks import (
    available_frameworks as available_frameworkss,
)
from ivy.functional.ivy.gradients import _variable
from ivy.functional.ivy.data_type import _get_function_list, _get_functions_from_string
from ivy_tests.test_ivy.test_frontends import NativeClass
from ivy_tests.test_ivy.helpers.structs import FrontendMethodData
from ivy.functional.frontends.torch.tensor import Tensor as torch_tensor
from ivy.functional.frontends.tensorflow.tensor import EagerTensor as tf_tensor
from ivy.functional.frontends.jax.devicearray import DeviceArray
from ivy.functional.frontends.numpy.ndarray.ndarray import ndarray
from .assertions import (
    value_test,
    check_unsupported_dtype,
)
from . import globals


try:
    os.environ["IVY_ROOT"] = ".ivy"
    import ivy.compiler.compiler as ic
except Exception:
    ic = types.SimpleNamespace()
    ic.compile = lambda func, args, kwargs: func


# Temporary (.so) configuration
def compiled_if_required(fn, test_compile=False, args=None, kwargs=None):
    if test_compile:
        fn = ic.compile(fn, args=args, kwargs=kwargs)
    return fn


available_frameworks = available_frameworkss()


def make_json_pickable(s):
    s = s.replace("builtins.bfloat16", "ivy.bfloat16")
    s = s.replace("jax._src.device_array.reconstruct_device_array", "jax.numpy.array")
    return s


def empty_func(*args, **kwargs):
    return None


try:
    from ivy.functional.backends.jax.general import (
        is_native_array as is_jax_native_array,
    )
except ImportError:
    is_jax_native_array = empty_func

try:
    from ivy.functional.backends.numpy.general import (
        is_native_array as is_numpy_native_array,
    )
except ImportError:
    is_numpy_native_array = empty_func

try:
    from ivy.functional.backends.tensorflow.general import (
        is_native_array as is_tensorflow_native_array,
    )
except ImportError:
    is_tensorflow_native_array = empty_func

try:
    from ivy.functional.backends.torch.general import (
        is_native_array as is_torch_native_array,
    )
except ImportError:
    is_torch_native_array = empty_func


# Function testing


def test_function(
    *,
    input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    test_flags: FunctionTestFlags,
    fw: str,
    fn_name: str,
    rtol_: float = None,
    atol_: float = 1e-06,
    test_values: bool = True,
    xs_grad_idxs=None,
    ret_grad_idxs=None,
    ground_truth_backend: str,
    on_device: str,
    return_flat_np_arrays: bool = False,
    **all_as_kwargs_np,
):
    """Tests a function that consumes (or returns) arrays for the current backend
    by comparing the result with numpy.

    Parameters
    ----------
    input_dtypes
        data types of the input arguments in order.
    test_flags
        FunctionTestFlags object that stores all testing flags, including:
        num_positional_args, with_out, instance_method, as_variable,
        native_arrays, container, gradient
    fw
        current backend (framework).
    fn_name
        name of the function to test.
    rtol_
        relative tolerance value.
    atol_
        absolute tolerance value.
    test_values
        if True, test for the correctness of the resulting values.
    xs_grad_idxs
        Indices of the input arrays to compute gradients with respect to. If None,
        gradients are returned with respect to all input arrays. (Default value = None)
    ret_grad_idxs
        Indices of the returned arrays for which to return computed gradients. If None,
        gradients are returned for all returned arrays. (Default value = None)
    ground_truth_backend
        Ground Truth Backend to compare the result-values.
    on_device
        The device on which to create arrays
    return_flat_np_arrays
        If test_values is False, this flag dictates whether the original returns are
        returned, or whether the flattened numpy arrays are returned.
    all_as_kwargs_np
        input arguments to the function as keyword arguments.

    Returns
    -------
    ret
        optional, return value from the function
    ret_gt
        optional, return value from the Ground Truth function

    Examples
    --------
    >>> input_dtypes = 'float64'
    >>> as_variable_flags = False
    >>> with_out = False
    >>> num_positional_args = 0
    >>> native_array_flags = False
    >>> container_flags = False
    >>> instance_method = False
    >>> test_flags = FunctionTestFlags(num_positional_args, with_out,
        instance_method,
        as_variable,
        native_arrays,
        container_flags,
        none)
    >>> fw = "torch"
    >>> fn_name = "abs"
    >>> x = np.array([-1])
    >>> test_function(input_dtypes, test_flags, fw, fn_name, x=x)

    >>> input_dtypes = ['float64', 'float32']
    >>> as_variable_flags = [False, True]
    >>> with_out = False
    >>> num_positional_args = 1
    >>> native_array_flags = [True, False]
    >>> container_flags = [False, False]
    >>> instance_method = False
    >>> test_flags = FunctionTestFlags(num_positional_args, with_out,
        instance_method,
        as_variable,
        native_arrays,
        container_flags,
        none)
    >>> fw = "numpy"
    >>> fn_name = "add"
    >>> x1 = np.array([1, 3, 4])
    >>> x2 = np.array([-3, 15, 24])
    >>> test_function(input_dtypes, test_flags, fw, fn_name, x1=x1, x2=x2)
    """
    if isinstance(globals.CURRENT_GROUND_TRUTH_BACKEND, list):
        # override the ground truth in favor of multiversion
        ground_truth_backend = globals.CURRENT_GROUND_TRUTH_BACKEND

    # split the arguments into their positional and keyword components
    args_np, kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=test_flags.num_positional_args, kwargs=all_as_kwargs_np
    )

    # extract all arrays from the arguments and keyword arguments
    arg_np_vals, args_idxs, c_arg_vals = _get_nested_np_arrays(args_np)
    kwarg_np_vals, kwargs_idxs, c_kwarg_vals = _get_nested_np_arrays(kwargs_np)

    # make all lists equal in length
    num_arrays = c_arg_vals + c_kwarg_vals
    if len(input_dtypes) < num_arrays:
        input_dtypes = [input_dtypes[0] for _ in range(num_arrays)]
    if len(test_flags.as_variable) < num_arrays:
        test_flags.as_variable = [test_flags.as_variable[0] for _ in range(num_arrays)]
    if len(test_flags.native_arrays) < num_arrays:
        test_flags.native_arrays = [
            test_flags.native_arrays[0] for _ in range(num_arrays)
        ]
    if len(test_flags.container) < num_arrays:
        test_flags.container = [test_flags.container[0] for _ in range(num_arrays)]

    # update variable flags to be compatible with float dtype and with_out args
    test_flags.as_variable = [
        v if ivy.is_float_dtype(d) and not test_flags.with_out else False
        for v, d in zip(test_flags.as_variable, input_dtypes)
    ]

    # update instance_method flag to only be considered if the
    # first term is either an ivy.Array or ivy.Container
    instance_method = test_flags.instance_method and (
        not test_flags.native_arrays[0] or test_flags.container[0]
    )

    fn = getattr(ivy, fn_name)
    if gradient_incompatible_function(fn=fn):
        return

    args, kwargs, num_arg_vals, args_idxs, kwargs_idxs = create_args_kwargs(
        args_np=args_np,
        arg_np_vals=arg_np_vals,
        args_idxs=args_idxs,
        kwargs_np=kwargs_np,
        kwarg_np_vals=kwarg_np_vals,
        kwargs_idxs=kwargs_idxs,
        input_dtypes=input_dtypes,
        test_flags=test_flags,
        on_device=on_device,
    )

    if ("out" in kwargs or test_flags.with_out) and "out" not in inspect.signature(
        fn
    ).parameters:
        raise Exception(f"Function {fn_name} does not have an out parameter")
    # run either as an instance method or from the API directly
    instance = None
    if instance_method:
        is_instance = [
            (not native_flag) or container_flag
            for native_flag, container_flag in zip(
                test_flags.native_arrays, test_flags.container
            )
        ]
        arg_is_instance = is_instance[:num_arg_vals]
        kwarg_is_instance = is_instance[num_arg_vals:]
        if arg_is_instance and max(arg_is_instance):
            i = 0
            for i, a in enumerate(arg_is_instance):
                if a:
                    break
            instance_idx = args_idxs[i]
            instance = ivy.index_nest(args, instance_idx)
            args = ivy.copy_nest(args, to_mutable=False)
            ivy.prune_nest_at_index(args, instance_idx)
        else:
            i = 0
            for i, a in enumerate(kwarg_is_instance):
                if a:
                    break
            instance_idx = kwargs_idxs[i]
            instance = ivy.index_nest(kwargs, instance_idx)
            kwargs = ivy.copy_nest(kwargs, to_mutable=False)
            ivy.prune_nest_at_index(kwargs, instance_idx)
        if test_flags.test_compile:
            instance_func = lambda instance, *args, **kwargs: instance.__getattribute__(
                fn_name
            )(*args, **kwargs)
            args = [instance, *args]
        else:
            instance_func = instance.__getattribute__(fn_name)
        ret, ret_np_flat = get_ret_and_flattened_np_array(
            instance_func,
            *args,
            test_compile=test_flags.test_compile,
            **kwargs,
        )
    else:
        ret, ret_np_flat = get_ret_and_flattened_np_array(
            ivy.__dict__[fn_name], *args, test_compile=test_flags.test_compile, **kwargs
        )
    # assert idx of return if the idx of the out array provided
    if test_flags.with_out and not test_flags.test_compile:
        test_ret = (
            ret[getattr(ivy.__dict__[fn_name], "out_index")]
            if hasattr(ivy.__dict__[fn_name], "out_index")
            else ret
        )
        out = ivy.nested_map(
            test_ret, ivy.zeros_like, to_mutable=True, include_derived=True
        )
        if instance_method:
            ret, ret_np_flat = get_ret_and_flattened_np_array(
                instance.__getattribute__(fn_name), *args, **kwargs, out=out
            )
        else:
            ret, ret_np_flat = get_ret_and_flattened_np_array(
                ivy.__dict__[fn_name], *args, **kwargs, out=out
            )
        test_ret = (
            ret[getattr(ivy.__dict__[fn_name], "out_index")]
            if hasattr(ivy.__dict__[fn_name], "out_index")
            else ret
        )
        assert not ivy.nested_any(
            ivy.nested_multi_map(lambda x, _: x[0] is x[1], [test_ret, out]),
            lambda x: not x,
        )
        if not max(test_flags.container) and ivy.native_inplace_support:
            # these backends do not always support native inplace updates
            assert not ivy.nested_any(
                ivy.nested_multi_map(
                    lambda x, _: x[0].data is x[1].data, [test_ret, out]
                ),
                lambda x: not x,
            )
    # compute the return with a Ground Truth backend

    if isinstance(ground_truth_backend, list):
        process = ground_truth_backend[1]

        try:
            process.stdin.write(jsonpickle.dumps(args_np) + "\n")
            process.stdin.write(jsonpickle.dumps(arg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(args_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_np) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwarg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(input_dtypes) + "\n")
            process.stdin.write(jsonpickle.dumps(test_flags) + "\n")
            process.stdin.write(jsonpickle.dumps(fn_name) + "\n")
            process.stdin.flush()
        except Exception as e:
            print("Something bad happened to the subprocess, here are the logs:\n\n")

            print(process.stdout.readlines())
            raise e
        ground_ret = process.stdout.readline()
        if ground_ret:
            ground_ret = jsonpickle.loads(make_json_pickable(ground_ret))
        else:
            print(process.stderr.readlines())
            raise Exception
        ret_from_gt, ret_np_from_gt_flat, fw_list = ground_ret

    else:
        ivy.set_backend(ground_truth_backend)
        ivy.set_default_device(on_device)
        try:
            fn = getattr(ivy, fn_name)
            args, kwargs, *_ = create_args_kwargs(
                args_np=args_np,
                arg_np_vals=arg_np_vals,
                args_idxs=args_idxs,
                kwargs_np=kwargs_np,
                kwargs_idxs=kwargs_idxs,
                kwarg_np_vals=kwarg_np_vals,
                input_dtypes=input_dtypes,
                test_flags=test_flags,
                on_device=on_device,
            )
            ret_from_gt, ret_np_from_gt_flat = get_ret_and_flattened_np_array(
                ivy.__dict__[fn_name],
                *args,
                test_compile=test_flags.test_compile,
                **kwargs,
            )
            if test_flags.with_out and not test_flags.test_compile:
                test_ret_from_gt = (
                    ret_from_gt[getattr(ivy.__dict__[fn_name], "out_index")]
                    if hasattr(ivy.__dict__[fn_name], "out_index")
                    else ret_from_gt
                )
                out_from_gt = ivy.nested_map(
                    test_ret_from_gt,
                    ivy.zeros_like,
                    to_mutable=True,
                    include_derived=True,
                )
                ret_from_gt, ret_np_from_gt_flat = get_ret_and_flattened_np_array(
                    ivy.__dict__[fn_name],
                    *args,
                    test_compile=test_flags.test_compile,
                    **kwargs,
                    out=out_from_gt,
                )
        except Exception as e:
            ivy.previous_backend()
            raise e
        fw_list = gradient_unsupported_dtypes(fn=ivy.__dict__[fn_name])
        gt_returned_array = isinstance(ret_from_gt, ivy.Array)
        if gt_returned_array:
            ret_from_gt_device = ivy.dev(ret_from_gt)
        ivy.previous_backend()
    # gradient test
    fw = ivy.current_backend_str()
    if (
        test_flags.test_gradients
        and not fw == "numpy"
        and not instance_method
        and "bool" not in input_dtypes
        and not any(ivy.is_complex_dtype(d) for d in input_dtypes)
    ):
        if fw in fw_list:
            if ivy.nested_argwhere(
                all_as_kwargs_np,
                lambda x: x.dtype in fw_list[fw] if isinstance(x, np.ndarray) else None,
            ):
                pass
            else:
                gradient_test(
                    fn=fn_name,
                    all_as_kwargs_np=all_as_kwargs_np,
                    args_np=args_np,
                    kwargs_np=kwargs_np,
                    input_dtypes=input_dtypes,
                    test_flags=test_flags,
                    rtol_=rtol_,
                    atol_=atol_,
                    xs_grad_idxs=xs_grad_idxs,
                    ret_grad_idxs=ret_grad_idxs,
                    ground_truth_backend=ground_truth_backend,
                    on_device=on_device,
                )

        else:
            gradient_test(
                fn=fn_name,
                all_as_kwargs_np=all_as_kwargs_np,
                args_np=args_np,
                kwargs_np=kwargs_np,
                input_dtypes=input_dtypes,
                test_flags=test_flags,
                rtol_=rtol_,
                atol_=atol_,
                xs_grad_idxs=xs_grad_idxs,
                ret_grad_idxs=ret_grad_idxs,
                ground_truth_backend=ground_truth_backend,
                on_device=on_device,
            )

    if gt_returned_array:
        ret_device = ivy.dev(ret)

        assert (
            ret_device == ret_from_gt_device
        ), f"ground truth backend ({ground_truth_backend}) returned array on device {ret_from_gt_device} but target backend ({ivy.backend}) returned array on device {ret_device}"
        assert (
            ret_device == on_device
        ), f"device is set to {on_device}, but ground truth produced array on {ret_device}"

    # assuming value test will be handled manually in the test function
    if not test_values:
        if return_flat_np_arrays:
            return ret_np_flat, ret_np_from_gt_flat
        return ret, ret_from_gt

    if isinstance(rtol_, dict):
        rtol_ = _get_framework_rtol(rtol_, fw)
    if isinstance(atol_, dict):
        atol_ = _get_framework_atol(atol_, fw)

    # value test
    value_test(
        ret_np_flat=ret_np_flat,
        ret_np_from_gt_flat=ret_np_from_gt_flat,
        rtol=rtol_,
        atol=atol_,
        ground_truth_backend=ground_truth_backend,
    )


def test_frontend_function(
    *,
    input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    test_flags: pf.frontend_function_flags,
    on_device="cpu",
    frontend: str,
    fn_tree: str,
    rtol: float = None,
    atol: float = 1e-06,
    test_values: bool = True,
    **all_as_kwargs_np,
):
    """Tests a frontend function for the current backend by comparing the result with
    the function in the associated framework.

    Parameters
    ----------
    input_dtypes
        data types of the input arguments in order.
    all_aliases
        a list of strings containing all aliases for that function
        in the current frontend with their full namespaces.
    frontend
        current frontend (framework).
    fn_tree
        Path to function in frontend framework namespace.
    rtol
        relative tolerance value.
    atol
        absolute tolerance value.
    test_values
        if True, test for the correctness of the resulting values.
    all_as_kwargs_np
        input arguments to the function as keyword arguments.

    Returns
    -------
    ret
        optional, return value from the function
    ret_np
        optional, return value from the Numpy function
    """
    assert (
        not test_flags.with_out or not test_flags.inplace
    ), "only one of with_out or with_inplace can be set as True"

    # split the arguments into their positional and keyword components
    args_np, kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=test_flags.num_positional_args, kwargs=all_as_kwargs_np
    )

    # extract all arrays from the arguments and keyword arguments
    arg_np_vals, args_idxs, c_arg_vals = _get_nested_np_arrays(args_np)
    kwarg_np_vals, kwargs_idxs, c_kwarg_vals = _get_nested_np_arrays(kwargs_np)

    # make all lists equal in length
    num_arrays = c_arg_vals + c_kwarg_vals
    if len(input_dtypes) < num_arrays:
        input_dtypes = [input_dtypes[0] for _ in range(num_arrays)]
    if len(test_flags.as_variable) < num_arrays:
        test_flags.as_variable = [test_flags.as_variable[0] for _ in range(num_arrays)]
    if len(test_flags.native_arrays) < num_arrays:
        test_flags.native_arrays = [
            test_flags.native_arrays[0] for _ in range(num_arrays)
        ]

    # update var flags to be compatible with float dtype and with_out args
    test_flags.as_variable = [
        v if ivy.is_float_dtype(d) and not test_flags.with_out else False
        for v, d in zip(test_flags.as_variable, input_dtypes)
    ]

    # frontend function
    # parse function name and frontend submodules (jax.lax, jax.numpy etc.)
    if isinstance(frontend, list):
        frontend, frontend_proc = frontend
    split_index = fn_tree.rfind(".")
    frontend_submods, fn_name = fn_tree[:split_index], fn_tree[split_index + 1 :]
    function_module = importlib.import_module(frontend_submods)
    frontend_fn = getattr(function_module, fn_name)

    args, kwargs, *_ = create_args_kwargs(
        args_np=args_np,
        arg_np_vals=arg_np_vals,
        args_idxs=args_idxs,
        kwargs_np=kwargs_np,
        kwarg_np_vals=kwarg_np_vals,
        kwargs_idxs=kwargs_idxs,
        input_dtypes=input_dtypes,
        test_flags=test_flags,
        on_device=on_device,
    )
    args_ivy, kwargs_ivy = ivy.args_to_ivy(*args, **kwargs)

    # check and replace NativeClass object in arguments with ivy counterparts
    from ivy_tests.test_ivy.test_frontends.test_numpy import convnumpy

    convs = {"numpy": convnumpy}

    if "torch" in available_frameworks:
        from ivy_tests.test_ivy.test_frontends.test_torch import convtorch

        convs["torch"] = convtorch

    if "tensorflow" in available_frameworks:
        from ivy_tests.test_ivy.test_frontends.test_tensorflow import convtensor

        convs["tensorflow"] = convtensor

    if "jax" in available_frameworks:
        from ivy_tests.test_ivy.test_frontends.test_jax import convjax

        convs["jax"] = convjax

    if frontend.split("/")[0] in convs:
        conv = convs[frontend.split("/")[0]]
        args = ivy.nested_map(args, fn=conv, include_derived=True)
        kwargs = ivy.nested_map(kwargs, fn=conv, include_derived=True)

    # Make copy for arguments for functions that might use
    # inplace update by default
    copy_kwargs = copy.deepcopy(kwargs)
    copy_args = copy.deepcopy(args)
    # strip the decorator to get an Ivy array
    # ToDo, fix testing for jax frontend for x32
    if frontend.split("/")[0] == "jax":
        importlib.import_module("ivy.functional.frontends.jax").config.update(
            "jax_enable_x64", True
        )
    ret = get_frontend_ret(frontend_fn, *args_ivy, **kwargs_ivy)
    if test_flags.with_out:
        if not inspect.isclass(ret):
            is_ret_tuple = issubclass(ret.__class__, tuple)
        else:
            is_ret_tuple = issubclass(ret, tuple)
        if is_ret_tuple:
            ret = ivy.nested_map(
                ret,
                lambda _x: ivy.array(_x) if not ivy.is_array(_x) else _x,
                include_derived=True,
            )
        elif not ivy.is_array(ret):
            ret = ivy.array(ret)
        out = ret
        # pass return value to out argument
        # check if passed reference is correctly updated
        kwargs["out"] = out
        if is_ret_tuple:
            flatten_ret = flatten(ret=ret)
            flatten_out = flatten(ret=out)
            for ret_array, out_array in zip(flatten_ret, flatten_out):
                if ivy.native_inplace_support:
                    assert ret_array.data is out_array.data
                assert ret_array is out_array
        else:
            if ivy.native_inplace_support:
                assert ret.data is out.data
            assert ret is out
    elif test_flags.inplace:
        assert not isinstance(ret, tuple)
        assert ivy.is_array(ret)
        if "inplace" in list(inspect.signature(frontend_fn).parameters.keys()):
            # the function provides optional inplace update
            # set inplace update to be True and check
            # if returned reference is inputted reference
            # and if inputted reference's content is correctly updated
            copy_kwargs["inplace"] = True
            first_array = ivy.func_wrapper._get_first_array(*copy_args, **copy_kwargs)
            ret_ = get_frontend_ret(frontend_fn, *copy_args, **copy_kwargs)
            assert first_array is ret_
        else:
            # the function provides inplace update by default
            # check if returned reference is inputted reference
            first_array = ivy.func_wrapper._get_first_array(*args, **kwargs)
            ret_ = get_frontend_ret(frontend_fn, *args, **kwargs)
            assert first_array is ret_
            args, kwargs = copy_args, copy_kwargs

    # create NumPy args
    args_np = ivy.nested_map(
        args_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )
    kwargs_np = ivy.nested_map(
        kwargs_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )

    if "/" in frontend and not framework_comparator(frontend):
        # multiversion zone, changes made in non-multiversion zone should
        # be applied here too

        try:
            # compute the return via the frontend framework
            module_name = fn_tree[25 : fn_tree.rfind(".")]

            pickle_dict = {"a": args_np, "b": kwargs_np}
            process = frontend_proc
            z = make_json_pickable(jsonpickle.dumps(pickle_dict))
            try:
                process.stdin.write(z + "\n")
                process.stdin.write(module_name + "\n")
                process.stdin.write(fn_name + "\n")
                process.stdin.flush()
            except Exception as e:
                print(
                    "Something bad happened to the subprocess, here are the logs:\n\n"
                )
                print(process.stdout.readlines())
                raise e
            frontend_ret = process.stdout.readline()
            if frontend_ret:
                frontend_ret = jsonpickle.loads(make_json_pickable(frontend_ret))
            else:
                print(process.stderr.readlines())
                raise Exception
            if ivy.isscalar(frontend_ret):
                frontend_ret_np_flat = [np.asarray(frontend_ret)]
            else:
                frontend_ret = ivy.to_ivy(frontend_ret)
                # tuplify the frontend return
                if not isinstance(frontend_ret, tuple):
                    frontend_ret = (frontend_ret,)
                frontend_ret_idxs = ivy.nested_argwhere(
                    frontend_ret,
                    lambda x: isinstance(x, np.ndarray) or isinstance(x, ivy.Array),
                )
                frontend_ret_flat = ivy.multi_index_nest(
                    frontend_ret, frontend_ret_idxs
                )
                frontend_ret_np_flat = [ivy.to_numpy(x) for x in frontend_ret_flat]

        except Exception as e:
            ivy.previous_backend()
            raise e

    else:
        # non-multiversion zone, changes made here should be
        # applied to multiversion zone too

        # temporarily set frontend framework as backend
        ivy.set_backend(frontend.split("/")[0])
        try:
            # create frontend framework args
            args_frontend = ivy.nested_map(
                args_np,
                lambda x: ivy.native_array(x)
                if isinstance(x, np.ndarray)
                else ivy.as_native_dtype(x)
                if isinstance(x, ivy.Dtype)
                else x,
                shallow=False,
            )
            kwargs_frontend = ivy.nested_map(
                kwargs_np,
                lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
                shallow=False,
            )

            # change ivy dtypes to native dtypes
            if "dtype" in kwargs_frontend:
                kwargs_frontend["dtype"] = ivy.as_native_dtype(kwargs_frontend["dtype"])

            # change ivy device to native devices
            if "device" in kwargs_frontend:
                kwargs_frontend["device"] = ivy.as_native_dev(kwargs_frontend["device"])

            # check and replace the NativeClass objects in arguments
            # with true counterparts
            args_frontend = ivy.nested_map(
                args_frontend, fn=convtrue, include_derived=True, max_depth=10
            )
            kwargs_frontend = ivy.nested_map(
                kwargs_frontend, fn=convtrue, include_derived=True, max_depth=10
            )

            # compute the return via the frontend framework
            module_name = fn_tree[25 : fn_tree.rfind(".")]
            frontend_fw = importlib.import_module(module_name)
            frontend_ret = frontend_fw.__dict__[fn_name](
                *args_frontend, **kwargs_frontend
            )

            if ivy.isscalar(frontend_ret):
                frontend_ret_np_flat = [np.asarray(frontend_ret)]
            else:
                # tuplify the frontend return
                if not isinstance(frontend_ret, tuple):
                    frontend_ret = (frontend_ret,)
                frontend_ret_idxs = ivy.nested_argwhere(
                    frontend_ret, ivy.is_native_array
                )
                frontend_ret_flat = ivy.multi_index_nest(
                    frontend_ret, frontend_ret_idxs
                )
                frontend_ret_np_flat = [ivy.to_numpy(x) for x in frontend_ret_flat]
            # unset frontend framework from backend
            ivy.previous_backend()
        except Exception as e:
            ivy.previous_backend()
            raise e

    ret_np_flat = flatten_and_to_np(ret=ret)

    # assuming value test will be handled manually in the test function
    if not test_values:
        return ret, frontend_ret

    if isinstance(rtol, dict):
        rtol = _get_framework_rtol(rtol, ivy.backend)
    if isinstance(atol, dict):
        atol = _get_framework_atol(atol, ivy.backend)

    value_test(
        ret_np_flat=ret_np_flat,
        ret_np_from_gt_flat=frontend_ret_np_flat,
        rtol=rtol,
        atol=atol,
        ground_truth_backend=frontend,
    )


# Method testing


def gradient_test(
    *,
    fn,
    all_as_kwargs_np,
    args_np,
    kwargs_np,
    input_dtypes,
    test_flags,
    test_compile: bool = False,
    rtol_: float = None,
    atol_: float = 1e-06,
    xs_grad_idxs=None,
    ret_grad_idxs=None,
    ground_truth_backend: str,
    on_device: str,
):
    def grad_fn(all_args):
        args, kwargs, i = all_args
        call_fn = ivy.__dict__[fn] if isinstance(fn, str) else fn[i]
        ret = compiled_if_required(
            call_fn, test_compile=test_compile, args=args, kwargs=kwargs
        )(*args, **kwargs)
        return ivy.nested_map(ret, ivy.mean, include_derived=True)

    # extract all arrays from the arguments and keyword arguments
    arg_np_vals, args_idxs, c_arg_vals = _get_nested_np_arrays(args_np)
    kwarg_np_vals, kwargs_idxs, c_kwarg_vals = _get_nested_np_arrays(kwargs_np)

    args, kwargs, _, args_idxs, kwargs_idxs = create_args_kwargs(
        args_np=args_np,
        arg_np_vals=arg_np_vals,
        args_idxs=args_idxs,
        kwargs_np=kwargs_np,
        kwarg_np_vals=kwarg_np_vals,
        kwargs_idxs=kwargs_idxs,
        input_dtypes=input_dtypes,
        test_flags=test_flags,
        on_device=on_device,
    )
    _, grads = ivy.execute_with_gradients(
        grad_fn,
        [args, kwargs, 0],
        xs_grad_idxs=xs_grad_idxs,
        ret_grad_idxs=ret_grad_idxs,
    )
    grads_np_flat = flatten_and_to_np(ret=grads)

    # compute the return with a Ground Truth backend

    if isinstance(ground_truth_backend, list):
        process = ground_truth_backend[1]
        try:
            process.stdin.write("2" + "\n")
            process.stdin.write(jsonpickle.dumps(args_np) + "\n")
            process.stdin.write(jsonpickle.dumps(arg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(args_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_np) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwarg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(input_dtypes) + "\n")
            process.stdin.write(jsonpickle.dumps(test_flags) + "\n")
            process.stdin.write(jsonpickle.dumps(fn) + "\n")
            process.stdin.write(jsonpickle.dumps(all_as_kwargs_np) + "\n")
            process.stdin.write(jsonpickle.dumps(grad_fn) + "\n")
            process.stdin.write(jsonpickle.dumps(xs_grad_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(ret_grad_idxs) + "\n")
            process.stdin.flush()
        except Exception as e:
            print("Something bad happened to the subprocess, here are the logs:\n\n")
            print(process.stdout.readlines())
            raise e
        ground_ret = process.stdout.readline()
        if ground_ret:
            ground_ret = jsonpickle.loads(make_json_pickable(ground_ret))
        else:
            print(process.stderr.readlines())
            raise Exception
        grads_np_from_gt_flat = ground_ret
    else:
        ivy.set_backend(ground_truth_backend)
        ivy.set_default_device(on_device)
        test_unsupported = check_unsupported_dtype(
            fn=ivy.__dict__[fn] if isinstance(fn, str) else fn[1],
            input_dtypes=input_dtypes,
            all_as_kwargs_np=all_as_kwargs_np,
        )
        if test_unsupported:
            return
        args, kwargs, _, args_idxs, kwargs_idxs = create_args_kwargs(
            args_np=args_np,
            arg_np_vals=arg_np_vals,
            args_idxs=args_idxs,
            kwargs_np=kwargs_np,
            kwarg_np_vals=kwarg_np_vals,
            kwargs_idxs=kwargs_idxs,
            input_dtypes=input_dtypes,
            test_flags=test_flags,
            on_device=on_device,
        )
        _, grads_from_gt = ivy.execute_with_gradients(
            grad_fn,
            [args, kwargs, 1],
            xs_grad_idxs=xs_grad_idxs,
            ret_grad_idxs=ret_grad_idxs,
        )
        grads_np_from_gt_flat = flatten_and_to_np(ret=grads_from_gt)
        ivy.previous_backend()

    assert len(grads_np_flat) == len(
        grads_np_from_gt_flat
    ), "result length mismatch: {} ({}) != {} ({})".format(
        grads_np_flat,
        len(grads_np_flat),
        grads_np_from_gt_flat,
        len(grads_np_from_gt_flat),
    )

    for grad_np_flat, grad_np_from_gt_flat in zip(grads_np_flat, grads_np_from_gt_flat):
        value_test(
            ret_np_flat=grad_np_flat,
            ret_np_from_gt_flat=grad_np_from_gt_flat,
            rtol=rtol_,
            atol=atol_,
            ground_truth_backend=ground_truth_backend,
        )


def test_method(
    *,
    init_input_dtypes: List[ivy.Dtype] = None,
    method_input_dtypes: List[ivy.Dtype] = None,
    init_all_as_kwargs_np: dict = None,
    method_all_as_kwargs_np: dict = None,
    init_flags: pf.MethodTestFlags,
    method_flags: pf.MethodTestFlags,
    class_name: str,
    method_name: str = "__call__",
    init_with_v: bool = False,
    method_with_v: bool = False,
    rtol_: float = None,
    atol_: float = 1e-06,
    test_values: Union[bool, str] = True,
    test_gradients: bool = False,
    xs_grad_idxs=None,
    ret_grad_idxs=None,
    test_compile: bool = False,
    ground_truth_backend: str,
    on_device: str,
    return_flat_np_arrays: bool = False,
):
    """Tests a class-method that consumes (or returns) arrays for the current backend
    by comparing the result with numpy.

    Parameters
    ----------
    init_input_dtypes
        data types of the input arguments to the constructor in order.
    init_as_variable_flags
        dictates whether the corresponding input argument passed to the constructor
        should be treated as an ivy.Array.
    init_num_positional_args
        number of input arguments that must be passed as positional arguments to the
        constructor.
    init_native_array_flags
        dictates whether the corresponding input argument passed to the constructor
        should be treated as a native array.
    init_all_as_kwargs_np:
        input arguments to the constructor as keyword arguments.
    method_input_dtypes
        data types of the input arguments to the method in order.
    method_as_variable_flags
        dictates whether the corresponding input argument passed to the method should
        be treated as an ivy.Array.
    method_num_positional_args
        number of input arguments that must be passed as positional arguments to the
        method.
    method_native_array_flags
        dictates whether the corresponding input argument passed to the method should
        be treated as a native array.
    method_container_flags
        dictates whether the corresponding input argument passed to the method should
        be treated as an ivy Container.
    method_all_as_kwargs_np:
        input arguments to the method as keyword arguments.
    class_name
        name of the class to test.
    method_name
        name of tthe method to test.
    init_with_v
        if the class being tested is an ivy.Module, then setting this flag as True will
        call the constructor with the variables v passed explicitly.
    method_with_v
        if the class being tested is an ivy.Module, then setting this flag as True will
        call the method with the variables v passed explicitly.
    rtol_
        relative tolerance value.
    atol_
        absolute tolerance value.
    test_values
        can be a bool or a string to indicate whether correctness of values should be
        tested. If the value is `with_v`, shapes are tested but not values.
    test_gradients
        if True, test for the correctness of gradients.
    xs_grad_idxs
        Indices of the input arrays to compute gradients with respect to. If None,
        gradients are returned with respect to all input arrays. (Default value = None)
    ret_grad_idxs
        Indices of the returned arrays for which to return computed gradients. If None,
        gradients are returned for all returned arrays. (Default value = None)
    test_compile
        If True, test for the correctness of compilation.
    ground_truth_backend
        Ground Truth Backend to compare the result-values.
    device_
        The device on which to create arrays.
    return_flat_np_arrays
        If test_values is False, this flag dictates whether the original returns are
        returned, or whether the flattened numpy arrays are returned.

    Returns
    -------
    ret
        optional, return value from the function
    ret_gt
        optional, return value from the Ground Truth function
    """
    if isinstance(globals.CURRENT_GROUND_TRUTH_BACKEND, list):
        # override the ground truth in favor of multiversion
        ground_truth_backend = globals.CURRENT_GROUND_TRUTH_BACKEND
        ground_truth_backend = globals.CURRENT_GROUND_TRUTH_BACKEND

    init_input_dtypes = ivy.default(init_input_dtypes, [])

    # Constructor arguments #
    init_all_as_kwargs_np = ivy.default(init_all_as_kwargs_np, dict())
    # split the arguments into their positional and keyword components
    args_np_constructor, kwargs_np_constructor = kwargs_to_args_n_kwargs(
        num_positional_args=init_flags.num_positional_args,
        kwargs=init_all_as_kwargs_np,
    )

    # extract all arrays from the arguments and keyword arguments
    con_arg_np_vals, con_args_idxs, con_c_arg_vals = _get_nested_np_arrays(
        args_np_constructor
    )
    con_kwarg_np_vals, con_kwargs_idxs, con_c_kwarg_vals = _get_nested_np_arrays(
        kwargs_np_constructor
    )

    # make all lists equal in length
    num_arrays_constructor = con_c_arg_vals + con_c_kwarg_vals
    if len(init_input_dtypes) < num_arrays_constructor:
        init_input_dtypes = [
            init_input_dtypes[0] for _ in range(num_arrays_constructor)
        ]
    if len(init_flags.as_variable) < num_arrays_constructor:
        init_flags.as_variable = [
            init_flags.as_variable[0] for _ in range(num_arrays_constructor)
        ]
    if len(init_flags.native_arrays) < num_arrays_constructor:
        init_flags.native_arrays = [
            init_flags.native_arrays[0] for _ in range(num_arrays_constructor)
        ]

    # update variable flags to be compatible with float dtype
    init_flags.as_variable = [
        v if ivy.is_float_dtype(d) else False
        for v, d in zip(init_flags.as_variable, init_input_dtypes)
    ]

    # Create Args
    args_constructor, kwargs_constructor, *_ = create_args_kwargs(
        args_np=args_np_constructor,
        arg_np_vals=con_arg_np_vals,
        args_idxs=con_args_idxs,
        kwargs_np=kwargs_np_constructor,
        kwarg_np_vals=con_kwarg_np_vals,
        kwargs_idxs=con_kwargs_idxs,
        input_dtypes=init_input_dtypes,
        test_flags=init_flags,
        on_device=on_device,
    )
    # end constructor #

    # method arguments #
    method_input_dtypes = ivy.default(method_input_dtypes, [])
    args_np_method, kwargs_np_method = kwargs_to_args_n_kwargs(
        num_positional_args=method_flags.num_positional_args,
        kwargs=method_all_as_kwargs_np,
    )

    # extract all arrays from the arguments and keyword arguments
    met_arg_np_vals, met_args_idxs, met_c_arg_vals = _get_nested_np_arrays(
        args_np_method
    )
    met_kwarg_np_vals, met_kwargs_idxs, met_c_kwarg_vals = _get_nested_np_arrays(
        kwargs_np_method
    )

    # make all lists equal in length
    num_arrays_method = met_c_arg_vals + met_c_kwarg_vals
    if len(method_input_dtypes) < num_arrays_method:
        method_input_dtypes = [method_input_dtypes[0] for _ in range(num_arrays_method)]
    if len(method_flags.as_variable) < num_arrays_method:
        method_flags.as_variable = [
            method_flags.as_variable[0] for _ in range(num_arrays_method)
        ]
    if len(method_flags.native_arrays) < num_arrays_method:
        method_flags.native_arrays = [
            method_flags.native_arrays[0] for _ in range(num_arrays_method)
        ]
    if len(method_flags.container) < num_arrays_method:
        method_flags.container = [
            method_flags.container[0] for _ in range(num_arrays_method)
        ]

    method_flags.as_variable = [
        v if ivy.is_float_dtype(d) else False
        for v, d in zip(method_flags.as_variable, method_input_dtypes)
    ]

    # Create Args
    args_method, kwargs_method, *_ = create_args_kwargs(
        args_np=args_np_method,
        arg_np_vals=met_arg_np_vals,
        args_idxs=met_args_idxs,
        kwargs_np=kwargs_np_method,
        kwarg_np_vals=met_kwarg_np_vals,
        kwargs_idxs=met_kwargs_idxs,
        input_dtypes=method_input_dtypes,
        test_flags=method_flags,
        on_device=on_device,
    )
    # End Method #

    # Run testing
    ins = ivy.__dict__[class_name](*args_constructor, **kwargs_constructor)
    # ToDo : remove this when the handle_method can properly compute unsupported dtypes
    if any(
        dtype in ivy.function_unsupported_dtypes(ins.__getattribute__(method_name))
        for dtype in method_input_dtypes
    ):
        return
    v_np = None
    if isinstance(ins, ivy.Module):
        if init_with_v:
            v = ivy.Container(
                ins._create_variables(device=on_device, dtype=method_input_dtypes[0])
            )
            ins = ivy.__dict__[class_name](*args_constructor, **kwargs_constructor, v=v)
        v = ins.__getattribute__("v")
        v_np = v.cont_map(lambda x, kc: ivy.to_numpy(x) if ivy.is_array(x) else x)
        if method_with_v:
            kwargs_method = dict(**kwargs_method, v=v)
    ret, ret_np_flat = get_ret_and_flattened_np_array(
        ins.__getattribute__(method_name),
        *args_method,
        test_compile=test_compile,
        **kwargs_method,
    )

    # Compute the return with a Ground Truth backend

    if isinstance(ground_truth_backend, list):
        process = ground_truth_backend[1]
        try:
            process.stdin.write("3" + "\n")
            process.stdin.write(jsonpickle.dumps(args_np_constructor) + "\n")
            process.stdin.write(jsonpickle.dumps(con_arg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(con_args_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_np_constructor) + "\n")
            process.stdin.write(jsonpickle.dumps(con_kwarg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(con_kwargs_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(init_input_dtypes) + "\n")
            process.stdin.write(jsonpickle.dumps(init_flags) + "\n")
            process.stdin.write(jsonpickle.dumps(args_np_method) + "\n")
            process.stdin.write(jsonpickle.dumps(met_arg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(met_args_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(kwargs_np_method) + "\n")
            process.stdin.write(jsonpickle.dumps(met_kwargs_idxs) + "\n")
            process.stdin.write(jsonpickle.dumps(met_kwarg_np_vals) + "\n")
            process.stdin.write(jsonpickle.dumps(method_input_dtypes) + "\n")
            process.stdin.write(jsonpickle.dumps(method_flags) + "\n")
            process.stdin.write(jsonpickle.dumps(class_name) + "\n")
            process.stdin.write(jsonpickle.dumps(method_name) + "\n")
            process.stdin.write(jsonpickle.dumps(method_input_dtypes) + "\n")
            process.stdin.write(jsonpickle.dumps(v_np) + "\n")

            process.stdin.flush()
        except Exception as e:
            print("Something bad happened to the subprocess, here are the logs:\n\n")
            print(process.stdout.readlines())
            raise e
        ground_ret = process.stdout.readline()
        if ground_ret:
            ground_ret = jsonpickle.loads(make_json_pickable(ground_ret))
        else:
            print(process.stderr.readlines())
            raise Exception
        ret_np_from_gt_flat, fw_list2 = ground_ret
        fw_list = gradient_unsupported_dtypes(fn=ins.__getattribute__(method_name))

        for k, v in fw_list2.items():
            if k not in fw_list:
                fw_list[k] = []
            fw_list[k].extend(v)
    else:
        ivy.set_backend(ground_truth_backend)
        ivy.set_default_device(on_device)
        args_gt_constructor, kwargs_gt_constructor, *_ = create_args_kwargs(
            args_np=args_np_constructor,
            arg_np_vals=con_arg_np_vals,
            args_idxs=con_args_idxs,
            kwargs_np=kwargs_np_constructor,
            kwarg_np_vals=con_kwarg_np_vals,
            kwargs_idxs=con_kwargs_idxs,
            input_dtypes=init_input_dtypes,
            test_flags=init_flags,
            on_device=on_device,
        )
        args_gt_method, kwargs_gt_method, *_ = create_args_kwargs(
            args_np=args_np_method,
            arg_np_vals=met_arg_np_vals,
            args_idxs=met_args_idxs,
            kwargs_np=kwargs_np_method,
            kwarg_np_vals=met_kwarg_np_vals,
            kwargs_idxs=met_kwargs_idxs,
            input_dtypes=method_input_dtypes,
            test_flags=method_flags,
            on_device=on_device,
        )
        ins_gt = ivy.__dict__[class_name](*args_gt_constructor, **kwargs_gt_constructor)
        # ToDo : remove this when the handle_method can properly compute unsupported dtypes
        if any(
            dtype
            in ivy.function_unsupported_dtypes(ins_gt.__getattribute__(method_name))
            for dtype in method_input_dtypes
        ):
            return
        if isinstance(ins_gt, ivy.Module):
            v_gt = v_np.cont_map(
                lambda x, kc: ivy.asarray(x) if isinstance(x, np.ndarray) else x
            )
            kwargs_gt_method = dict(**kwargs_gt_method, v=v_gt)
        ret_from_gt, ret_np_from_gt_flat = get_ret_and_flattened_np_array(
            ins_gt.__getattribute__(method_name),
            *args_gt_method,
            test_compile=test_compile,
            **kwargs_gt_method,
        )
        fw_list = gradient_unsupported_dtypes(fn=ins.__getattribute__(method_name))
        fw_list2 = gradient_unsupported_dtypes(fn=ins_gt.__getattribute__(method_name))
        for k, v in fw_list2.items():
            if k not in fw_list:
                fw_list[k] = []
            fw_list[k].extend(v)

        gt_returned_array = isinstance(ret_from_gt, ivy.Array)
        if gt_returned_array:
            ret_from_gt_device = ivy.dev(ret_from_gt)
        ivy.previous_backend()
    # gradient test

    if isinstance(ground_truth_backend, list):
        # multiversion
        ins_gt = ins

    fw = ivy.current_backend_str()
    if (
        test_gradients
        and not fw == "numpy"
        and "bool" not in method_input_dtypes
        and not any(ivy.is_complex_dtype(d) for d in method_input_dtypes)
    ):
        if fw in fw_list:
            if ivy.nested_argwhere(
                method_all_as_kwargs_np,
                lambda x: x.dtype in fw_list[fw] if isinstance(x, np.ndarray) else None,
            ):
                pass
            else:
                gradient_test(
                    fn=[
                        ins.__getattribute__(method_name),
                        ins_gt.__getattribute__(method_name),
                    ],
                    all_as_kwargs_np=method_all_as_kwargs_np,
                    args_np=args_np_method,
                    kwargs_np=kwargs_np_method,
                    input_dtypes=method_input_dtypes,
                    test_flags=method_flags,
                    test_compile=test_compile,
                    rtol_=rtol_,
                    atol_=atol_,
                    xs_grad_idxs=xs_grad_idxs,
                    ret_grad_idxs=ret_grad_idxs,
                    ground_truth_backend=ground_truth_backend,
                    on_device=on_device,
                )

        else:
            gradient_test(
                fn=[
                    ins.__getattribute__(method_name),
                    ins_gt.__getattribute__(method_name),
                ],
                all_as_kwargs_np=method_all_as_kwargs_np,
                args_np=args_np_method,
                kwargs_np=kwargs_np_method,
                input_dtypes=method_input_dtypes,
                test_flags=method_flags,
                test_compile=test_compile,
                rtol_=rtol_,
                atol_=atol_,
                xs_grad_idxs=xs_grad_idxs,
                ret_grad_idxs=ret_grad_idxs,
                ground_truth_backend=ground_truth_backend,
                on_device=on_device,
            )

    if gt_returned_array:
        ret_device = ivy.dev(ret)
        assert (
            ret_device == ret_from_gt_device
        ), f"ground truth backend ({ground_truth_backend}) returned array on device {ret_from_gt_device} but target backend ({ivy.backend}) returned array on device {ret_device}"
        assert (
            ret_device == on_device
        ), f"device is set to {on_device}, but ground truth produced array on {ret_device}"

    # assuming value test will be handled manually in the test function
    if not test_values:
        if return_flat_np_arrays:
            return ret_np_flat, ret_np_from_gt_flat
        return ret, ret_from_gt
    # value test

    if isinstance(rtol_, dict):
        rtol_ = _get_framework_rtol(rtol_, ivy.backend)
    if isinstance(atol_, dict):
        atol_ = _get_framework_atol(atol_, ivy.backend)

    value_test(
        ret_np_flat=ret_np_flat,
        ret_np_from_gt_flat=ret_np_from_gt_flat,
        rtol=rtol_,
        atol=atol_,
    )


def test_frontend_method(
    *,
    init_input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]] = None,
    method_input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    init_flags,
    method_flags,
    init_all_as_kwargs_np: dict = None,
    method_all_as_kwargs_np: dict,
    frontend: str,
    frontend_method_data: FrontendMethodData,
    on_device,
    rtol_: float = None,
    atol_: float = 1e-06,
    test_values: Union[bool, str] = True,
):
    """Tests a class-method that consumes (or returns) arrays for the current backend
    by comparing the result with numpy.

    Parameters
    ----------
    init_input_dtypes
        data types of the input arguments to the constructor in order.
    init_as_variable_flags
        dictates whether the corresponding input argument passed to the constructor
        should be treated as an ivy.Variable.
    init_num_positional_args
        number of input arguments that must be passed as positional arguments to the
        constructor.
    init_native_array_flags
        dictates whether the corresponding input argument passed to the constructor
        should be treated as a native array.
    init_all_as_kwargs_np:
        input arguments to the constructor as keyword arguments.
    method_input_dtypes
        data types of the input arguments to the method in order.
    method_all_as_kwargs_np:
        input arguments to the method as keyword arguments.
    frontend
        current frontend (framework).
    rtol_
        relative tolerance value.
    atol_
        absolute tolerance value.
    test_values
        can be a bool or a string to indicate whether correctness of values should be
        tested. If the value is `with_v`, shapes are tested but not values.

    Returns
    -------
    ret
        optional, return value from the function
    ret_gt
        optional, return value from the Ground Truth function
    """
    if isinstance(frontend, list):
        frontend, frontend_proc = frontend

    # Constructor arguments #

    args_np_constructor, kwargs_np_constructor = kwargs_to_args_n_kwargs(
        num_positional_args=init_flags.num_positional_args,
        kwargs=init_all_as_kwargs_np,
    )

    # extract all arrays from the arguments and keyword arguments
    con_arg_np_vals, con_args_idxs, con_c_arg_vals = _get_nested_np_arrays(
        args_np_constructor
    )
    con_kwarg_np_vals, con_kwargs_idxs, con_c_kwarg_vals = _get_nested_np_arrays(
        kwargs_np_constructor
    )

    # make all lists equal in length
    num_arrays_constructor = con_c_arg_vals + con_c_kwarg_vals
    if len(init_input_dtypes) < num_arrays_constructor:
        init_input_dtypes = [
            init_input_dtypes[0] for _ in range(num_arrays_constructor)
        ]
    if len(init_flags.as_variable) < num_arrays_constructor:
        init_flags.as_variable = [
            init_flags.as_variable[0] for _ in range(num_arrays_constructor)
        ]
    if len(init_flags.native_arrays) < num_arrays_constructor:
        init_flags.native_arrays = [
            init_flags.native_arrays[0] for _ in range(num_arrays_constructor)
        ]

    # update variable flags to be compatible with float dtype
    init_flags.as_variable = [
        v if ivy.is_float_dtype(d) else False
        for v, d in zip(init_flags.as_variable, init_input_dtypes)
    ]

    # Create Args
    args_constructor, kwargs_constructor, *_ = create_args_kwargs(
        args_np=args_np_constructor,
        arg_np_vals=con_arg_np_vals,
        args_idxs=con_args_idxs,
        kwargs_np=kwargs_np_constructor,
        kwarg_np_vals=con_kwarg_np_vals,
        kwargs_idxs=con_kwargs_idxs,
        input_dtypes=init_input_dtypes,
        test_flags=init_flags,
        on_device=on_device,
    )
    # End constructor #

    # Method arguments #
    args_np_method, kwargs_np_method = kwargs_to_args_n_kwargs(
        num_positional_args=method_flags.num_positional_args,
        kwargs=method_all_as_kwargs_np,
    )

    # extract all arrays from the arguments and keyword arguments
    met_arg_np_vals, met_args_idxs, met_c_arg_vals = _get_nested_np_arrays(
        args_np_method
    )
    met_kwarg_np_vals, met_kwargs_idxs, met_c_kwarg_vals = _get_nested_np_arrays(
        kwargs_np_method
    )

    # make all lists equal in length
    num_arrays_method = met_c_arg_vals + met_c_kwarg_vals
    if len(method_input_dtypes) < num_arrays_method:
        method_input_dtypes = [method_input_dtypes[0] for _ in range(num_arrays_method)]
    if len(method_flags.as_variable) < num_arrays_method:
        method_flags.as_variable = [
            method_flags.as_variable[0] for _ in range(num_arrays_method)
        ]
    if len(method_flags.native_arrays) < num_arrays_method:
        method_flags.native_arrays = [
            method_flags.native_arrays[0] for _ in range(num_arrays_method)
        ]

    method_flags.as_variable = [
        v if ivy.is_float_dtype(d) else False
        for v, d in zip(method_flags.as_variable, method_input_dtypes)
    ]

    # Create Args
    args_method, kwargs_method, *_ = create_args_kwargs(
        args_np=args_np_method,
        arg_np_vals=met_arg_np_vals,
        args_idxs=met_args_idxs,
        kwargs_np=kwargs_np_method,
        kwarg_np_vals=met_kwarg_np_vals,
        kwargs_idxs=met_kwargs_idxs,
        input_dtypes=method_input_dtypes,
        test_flags=method_flags,
        on_device=on_device,
    )
    # End Method #

    args_constructor_ivy, kwargs_constructor_ivy = ivy.args_to_ivy(
        *args_constructor, **kwargs_constructor
    )
    args_method_ivy, kwargs_method_ivy = ivy.args_to_ivy(*args_method, **kwargs_method)
    args_constructor_np = ivy.nested_map(
        args_constructor_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )
    kwargs_constructor_np = ivy.nested_map(
        kwargs_constructor_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )
    args_method_np = ivy.nested_map(
        args_method_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )
    kwargs_method_np = ivy.nested_map(
        kwargs_method_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
        shallow=False,
    )

    ivy_frontend_creation_fn = getattr(
        frontend_method_data.ivy_init_module, frontend_method_data.init_name
    )
    # Run testing
    ins = ivy_frontend_creation_fn(*args_constructor, **kwargs_constructor)
    ret, ret_np_flat = get_ret_and_flattened_np_array(
        ins.__getattribute__(frontend_method_data.method_name),
        *args_method,
        **kwargs_method,
    )

    # Compute the return with the native frontend framework
    if "/" in frontend and not framework_comparator(frontend):
        pickle_dict = {
            "a": args_constructor_np,
            "b": kwargs_constructor_np,
            "c": args_method_np,
            "d": kwargs_method_np,
            "e": frontend_method_data,
        }
        process = frontend_proc
        z = make_json_pickable(jsonpickle.dumps(pickle_dict))
        try:
            process.stdin.write("2" + "\n")
            process.stdin.write(z + "\n")
            process.stdin.flush()
        except Exception as e:
            print("Something bad happened to the subprocess, here are the logs:\n\n")
            print(process.stdout.readlines())
            raise e
        frontend_ret = process.stdout.readline()
        if frontend_ret:
            return_dict = jsonpickle.loads(make_json_pickable(frontend_ret))
            if return_dict["a"]:
                frontend_ret = ivy.to_ivy(return_dict["b"])
                # tuplify the frontend return
                if not isinstance(frontend_ret, tuple):
                    frontend_ret = (frontend_ret,)
                frontend_ret_idxs = ivy.nested_argwhere(
                    frontend_ret,
                    lambda x: isinstance(x, ivy.Array) or isinstance(x, np.ndarray),
                )
                frontend_ret_flat = ivy.multi_index_nest(
                    frontend_ret, frontend_ret_idxs
                )
                return_dict["b"] = [np.asarray(x) for x in frontend_ret_flat]
            frontend_ret_np_flat = return_dict["b"]
        else:
            print(process.stderr.readlines())
            raise Exception

    else:
        ivy.set_backend(frontend.split("/")[0])
        args_constructor_frontend = ivy.nested_map(
            args_constructor_np,
            lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
            shallow=False,
        )
        kwargs_constructor_frontend = ivy.nested_map(
            kwargs_constructor_np,
            lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
            shallow=False,
        )
        args_method_frontend = ivy.nested_map(
            args_method_np,
            lambda x: ivy.native_array(x)
            if isinstance(x, np.ndarray)
            else ivy.as_native_dtype(x)
            if isinstance(x, ivy.Dtype)
            else ivy.as_native_dev(x)
            if isinstance(x, ivy.Device)
            else x,
            shallow=False,
        )
        kwargs_method_frontend = ivy.nested_map(
            kwargs_method_np,
            lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
            shallow=False,
        )

        # change ivy dtypes to native dtypes
        if "dtype" in kwargs_method_frontend:
            kwargs_method_frontend["dtype"] = ivy.as_native_dtype(
                kwargs_method_frontend["dtype"]
            )

        # change ivy device to native devices
        if "device" in kwargs_method_frontend:
            kwargs_method_frontend["device"] = ivy.as_native_dev(
                kwargs_method_frontend["device"]
            )
        frontend_creation_fn = getattr(
            frontend_method_data.framework_init_module, frontend_method_data.init_name
        )
        ins_gt = frontend_creation_fn(
            *args_constructor_frontend, **kwargs_constructor_frontend
        )
        frontend_ret = ins_gt.__getattribute__(frontend_method_data.method_name)(
            *args_method_frontend, **kwargs_method_frontend
        )
        if frontend.split("/")[0] == "tensorflow" and isinstance(
            frontend_ret, tf.TensorShape
        ):
            frontend_ret_np_flat = [np.asarray(frontend_ret, dtype=np.int32)]
        elif ivy.isscalar(frontend_ret):
            frontend_ret_np_flat = [np.asarray(frontend_ret)]
        else:
            # tuplify the frontend return
            if not isinstance(frontend_ret, tuple):
                frontend_ret = (frontend_ret,)
            frontend_ret_idxs = ivy.nested_argwhere(frontend_ret, ivy.is_native_array)
            frontend_ret_flat = ivy.multi_index_nest(frontend_ret, frontend_ret_idxs)
            frontend_ret_np_flat = [ivy.to_numpy(x) for x in frontend_ret_flat]
        ivy.previous_backend()

    # assuming value test will be handled manually in the test function
    if not test_values:
        return ret, frontend_ret

    # value test
    if isinstance(rtol_, dict):
        rtol_ = _get_framework_rtol(rtol_, ivy.backend)
    if isinstance(atol_, dict):
        atol_ = _get_framework_atol(atol_, ivy.backend)

    value_test(
        ret_np_flat=ret_np_flat,
        ret_np_from_gt_flat=frontend_ret_np_flat,
        rtol=rtol_,
        atol=atol_,
        ground_truth_backend=frontend,
    )


# Helpers
DEFAULT_RTOL = None
DEFAULT_ATOL = 1e-06


def _get_framework_rtol(rtols: dict, current_fw: str):
    if current_fw in rtols.keys():
        return rtols[current_fw]
    return DEFAULT_RTOL


def _get_framework_atol(atols: dict, current_fw: str):
    if current_fw in atols.keys():
        return atols[current_fw]
    return DEFAULT_ATOL


def _get_nested_np_arrays(nest):
    """
    A helper function to search for a NumPy arrays in a nest
    Parameters
    ----------
    nest
        nest to search in.

    Returns
    -------
         Items found, indices, and total number of arrays found
    """
    indices = ivy.nested_argwhere(nest, lambda x: isinstance(x, np.ndarray))
    ret = ivy.multi_index_nest(nest, indices)
    return ret, indices, len(ret)


def create_args_kwargs(
    *,
    args_np,
    arg_np_vals,
    args_idxs,
    kwargs_np,
    kwarg_np_vals,
    kwargs_idxs,
    input_dtypes,
    test_flags: Union[pf.FunctionTestFlags, pf.MethodTestFlags],
    on_device,
):
    """Creates arguments and keyword-arguments for the function to test.

    Parameters
    ----------
    args_np
        A dictionary of arguments in Numpy.
    kwargs_np
        A dictionary of keyword-arguments in Numpy.
    input_dtypes
        data-types of the input arguments and keyword-arguments.

    Returns
    -------
    Arguments, Keyword-arguments, number of arguments, and indexes on arguments and
    keyword-arguments.
    """
    # create args
    args = ivy.copy_nest(args_np, to_mutable=False)
    ivy.set_nest_at_indices(
        args, args_idxs, test_flags.apply_flags(arg_np_vals, input_dtypes, on_device, 0)
    )

    # create kwargs
    kwargs = ivy.copy_nest(kwargs_np, to_mutable=False)
    ivy.set_nest_at_indices(
        kwargs,
        kwargs_idxs,
        test_flags.apply_flags(
            kwarg_np_vals, input_dtypes, on_device, len(arg_np_vals)
        ),
    )
    return args, kwargs, len(arg_np_vals), args_idxs, kwargs_idxs


def convtrue(argument):
    """Convert NativeClass in argument to true framework counter part"""
    if isinstance(argument, NativeClass):
        return argument._native_class
    return argument


def kwargs_to_args_n_kwargs(*, num_positional_args, kwargs):
    """Splits the kwargs into args and kwargs, with the first num_positional_args ported
    to args.
    """
    args = [v for v in list(kwargs.values())[:num_positional_args]]
    kwargs = {k: kwargs[k] for k in list(kwargs.keys())[num_positional_args:]}
    return args, kwargs


def flatten_fw_and_to_np(*, ret, fw):
    """Returns a flattened numpy version of the arrays in ret for a given framework."""
    if not isinstance(ret, tuple):
        ret = (ret,)
    if fw == "jax":
        ret_idxs = ivy.nested_argwhere(
            ret, lambda x: ivy.is_ivy_array(x) or is_jax_native_array(x)
        )
    elif fw == "numpy":
        ret_idxs = ivy.nested_argwhere(
            ret, lambda x: ivy.is_ivy_array(x) or is_numpy_native_array(x)
        )
    elif fw == "tensorflow":
        ret_idxs = ivy.nested_argwhere(
            ret, lambda x: ivy.is_ivy_array(x) or is_tensorflow_native_array(x)
        )
    else:
        ret_idxs = ivy.nested_argwhere(
            ret, lambda x: ivy.is_ivy_array(x) or is_torch_native_array(x)
        )
    if len(ret_idxs) == 0:
        ret_idxs = ivy.nested_argwhere(ret, ivy.isscalar)
        ret_flat = ivy.multi_index_nest(ret, ret_idxs)
        ret_flat = [
            ivy.asarray(x, dtype=ivy.Dtype(str(np.asarray(x).dtype))) for x in ret_flat
        ]
    else:
        ret_flat = ivy.multi_index_nest(ret, ret_idxs)
    # convert the return to NumPy
    ret_np_flat = [ivy.to_numpy(x) for x in ret_flat]
    return ret_np_flat


def flatten(*, ret):
    """Returns a flattened numpy version of the arrays in ret."""
    if not isinstance(ret, tuple):
        ret = (ret,)
    ret_idxs = ivy.nested_argwhere(ret, ivy.is_ivy_array)
    # no ivy array in the returned values, which means it returned scalar
    if len(ret_idxs) == 0:
        ret_idxs = ivy.nested_argwhere(ret, ivy.isscalar)
        ret_flat = ivy.multi_index_nest(ret, ret_idxs)
        ret_flat = [
            ivy.asarray(x, dtype=ivy.Dtype(str(np.asarray(x).dtype))) for x in ret_flat
        ]
    else:
        ret_flat = ivy.multi_index_nest(ret, ret_idxs)
    return ret_flat


def flatten_and_to_np(*, ret):
    # flatten the return
    ret_flat = flatten(ret=ret)
    return [ivy.to_numpy(x) for x in ret_flat]


def get_ret_and_flattened_np_array(fn, *args, test_compile: bool = False, **kwargs):
    """
    Runs func with args and kwargs, and returns the result along with its flattened
    version.
    """
    fn = compiled_if_required(fn, test_compile=test_compile, args=args, kwargs=kwargs)
    ret = fn(*args, **kwargs)

    def map_fn(x):
        if _is_frontend_array(x):
            return x.ivy_array
        elif ivy.is_native_array(x):
            return ivy.to_ivy(x)
        return x

    ret = ivy.nested_map(ret, map_fn, include_derived={tuple: True})
    return ret, flatten_and_to_np(ret=ret)


def get_frontend_ret(fn, *args, **kwargs):
    ret = fn(*args, **kwargs)
    ret = ivy.nested_map(ret, _frontend_array_to_ivy, include_derived={tuple: True})
    return ret


def args_to_container(array_args):
    array_args_container = ivy.Container({str(k): v for k, v in enumerate(array_args)})
    return array_args_container


def as_lists(*args):
    """Changes the elements in args to be of type list."""
    return (a if isinstance(a, list) else [a] for a in args)


def var_fn(x, *, dtype=None, device=None):
    """Returns x as a variable wrapping an Ivy Array with given dtype and device"""
    return _variable(ivy.array(x, dtype=dtype, device=device))


def gradient_incompatible_function(*, fn):
    return (
        not ivy.supports_gradients
        and hasattr(fn, "computes_gradients")
        and fn.computes_gradients
    )


def gradient_unsupported_dtypes(*, fn):
    visited = set()
    to_visit = [fn]
    out, res = {}, {}
    while to_visit:
        fn = to_visit.pop()
        if fn in visited:
            continue
        visited.add(fn)
        unsupported_grads = (
            fn.unsupported_gradients if hasattr(fn, "unsupported_gradients") else {}
        )
        for k, v in unsupported_grads.items():
            if k not in out:
                out[k] = []
            out[k].extend(v)
        # skip if it's not a function
        if not (inspect.isfunction(fn) or inspect.ismethod(fn)):
            continue
        fl = _get_function_list(fn)
        res = _get_functions_from_string(fl, __import__(fn.__module__))
        to_visit.extend(res)
    return out


def _is_frontend_array(x):
    return (
        isinstance(x, ndarray)
        or isinstance(x, torch_tensor)
        or isinstance(x, tf_tensor)
        or isinstance(x, DeviceArray)
    )


def _frontend_array_to_ivy(x):
    if _is_frontend_array(x):
        return x.ivy_array
    else:
        return x
