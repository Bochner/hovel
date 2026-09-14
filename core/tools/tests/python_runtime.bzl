"""Expose the declared Python interpreter and its runtime to non-Python tests."""

def _python_test_interpreter_impl(ctx):
    runtime = ctx.toolchains["@rules_python//python:toolchain_type"].py3_runtime
    if not runtime.interpreter:
        fail("Python tests require a hermetic Python toolchain")
    return [DefaultInfo(
        files = depset([runtime.interpreter]),
        runfiles = ctx.runfiles(
            files = [runtime.interpreter],
            transitive_files = runtime.files,
        ),
    )]

python_test_interpreter = rule(
    implementation = _python_test_interpreter_impl,
    toolchains = ["@rules_python//python:toolchain_type"],
)
