"""Helpers for writing tests"""

import contextlib
import os.path
import shutil
from typing import List, Callable, Iterator, Optional

from mypy import build
from mypy.errors import CompileError
from mypy.options import Options
from mypy.test.data import DataSuite, DataDrivenTestCase
from mypy.test.config import test_temp_dir
from mypy.test.helpers import assert_string_arrays_equal

from mypyc import genops
from mypyc.ops import FuncIR
from mypyc.test.config import test_data_prefix

# The builtins stub used during icode generation test cases.
ICODE_GEN_BUILTINS = os.path.join(test_data_prefix, 'fixtures/ir.py')


class MypycDataSuite(DataSuite):
    # Need to list no files, since this will be picked up as a suite of tests
    files = []  # type: List[str]
    data_prefix = test_data_prefix


def builtins_wrapper(func: Callable[[DataDrivenTestCase], None],
                     path: str) -> Callable[[DataDrivenTestCase], None]:
    """Decorate a function that implements a data-driven test case to copy an
    alternative builtins module implementation in place before performing the
    test case. Clean up after executing the test case.
    """
    return lambda testcase: perform_test(func, path, testcase)


@contextlib.contextmanager
def use_custom_builtins(builtins_path: str, testcase: DataDrivenTestCase) -> Iterator[None]:
    for path, _ in testcase.files:
        if os.path.basename(path) == 'builtins.pyi':
            default_builtins = False
            break
    else:
        # Use default builtins.
        builtins = os.path.join(test_temp_dir, 'builtins.pyi')
        shutil.copyfile(builtins_path, builtins)
        default_builtins = True

    # Actually peform the test case.
    yield None

    if default_builtins:
        # Clean up.
        os.remove(builtins)


def perform_test(func: Callable[[DataDrivenTestCase], None],
                 builtins_path: str, testcase: DataDrivenTestCase) -> None:
    for path, _ in testcase.files:
        if os.path.basename(path) == 'builtins.py':
            default_builtins = False
            break
    else:
        # Use default builtins.
        builtins = os.path.join(test_temp_dir, 'builtins.py')
        shutil.copyfile(builtins_path, builtins)
        default_builtins = True

    # Actually peform the test case.
    func(testcase)

    if default_builtins:
        # Clean up.
        os.remove(builtins)


def build_ir_for_single_file(input_lines: List[str]) -> List[FuncIR]:
    program_text = '\n'.join(input_lines)

    options = Options()
    options.show_traceback = True
    options.use_builtins_fixtures = True
    options.strict_optional = True
    options.python_version = (3, 6)
    options.export_types = True

    source = build.BuildSource('main', '__main__', program_text)
    # Construct input as a single single.
    # Parse and type check the input program.
    result = build.build(sources=[source],
                         options=options,
                         alt_lib_path=test_temp_dir)
    if result.errors:
        raise CompileError(result.errors)
    modules = genops.build_ir([result.files['__main__']], result.types)
    module = modules[0][1]
    return module.functions


def update_testcase_output(testcase: DataDrivenTestCase, output: List[str]) -> None:
    # TODO: backport this to mypy
    assert testcase.old_cwd is not None, "test was not properly set up"
    testcase_path = os.path.join(testcase.old_cwd, testcase.file)
    with open(testcase_path) as f:
        data_lines = f.read().splitlines()

    # We can't rely on the test line numbers to *find* the test, since
    # we might fix multiple tests in a run. So find it by the case
    # header. Give up if there are multiple tests with the same name.
    test_slug = '[case {}]'.format(testcase.name)
    if data_lines.count(test_slug) != 1:
        return
    start_idx = data_lines.index(test_slug)
    size = testcase.lastline - testcase.line - 1

    test = data_lines[start_idx:start_idx + size]
    out_start = test.index('[out]')
    test[out_start + 1:] = output
    data_lines[start_idx:start_idx + size] = test
    data = '\n'.join(data_lines)

    with open(testcase_path, 'w') as f:
        print(data, file=f)


def assert_test_output(testcase: DataDrivenTestCase, actual: List[str],
                       message: str,
                       expected: Optional[List[str]] = None) -> None:
    expected_output = expected if expected is not None else testcase.output
    if expected_output != actual and testcase.config.getoption('--update-data', False):
        update_testcase_output(testcase, actual)

    assert_string_arrays_equal(
        expected_output, actual,
        '{} ({}, line {})'.format(message, testcase.file, testcase.line))


def print_with_line_numbers(s: str) -> None:
    lines = s.splitlines()
    for i, line in enumerate(lines):
        print('%-4d %s' % (i, line))


def heading(text: str) -> None:
    print('=' * 20 + ' ' + text + ' ' + '=' * 20)


def show_c_error(cpath: str, output: bytes) -> None:
    heading('Generated C')
    with open(cpath) as f:
        print_with_line_numbers(f.read().rstrip())
    heading('End C')
    heading('Build output')
    print(output.decode('utf8').rstrip('\n'))
    heading('End output')
