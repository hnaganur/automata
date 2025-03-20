import argparse
import concurrent.futures
import multiprocessing as mp
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from queue import Queue

import pandas as pd

sys.dont_write_bytecode = True
os.environ['DONOTWRITEBYTECODE'] = '1'
PLATFORM = 'Windows' if sys.platform == 'win32' else 'Linux'
ISWINDOWS = PLATFORM == 'Windows'

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
    <head>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
        <title>Test Report</title>
        <h1 style="text-align: center;">{{title}}</h1>
        <hr>
    <style>
        body {
            background-color: #0f0f0f;
            color: #b4b0b0;
            font-family: sans-serif;
            letter-spacing: 0.75px;
            margin: 20px;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            -ms-font-smoothing: antialiased;
        }
        .content {
            display: grid;
            justify-content: center;
        }
        table {
            width: auto;
            table-layout: auto;
            border-collapse: collapse;
            border: 0px;
            margin-left: 40px
        }
        th {
            border-bottom: 1px solid #ddd;
        }
        td {
            border-bottom: 1px solid #353535;
        }
        .report th, .report td {
            padding: 5px;
            width: auto;
        }
        .report th:first-child, .report td:first-child {
            text-align: left;
            width: 80px;
        }
        .report th:not(:first-child), .report td:not(:first-child) {
            text-align: right;
        }
        .err th, .err td {
            padding-left: 50px;
            padding-right: 10px;
            text-align: left;
            height: 30px;
        }
        .err tr:last-child td {
            border: none;
        }
        footer {
            # position: fixed;
            bottom: 0;
            width: 100%;
            text-align: center;
            font-size: 12px;
            color: #999;
        }
        ul {
            list-style-type: none;
            margin: 0;
        }
        li {
            padding: 5px;
        }
    </style>
    </head>
    <body>
        <div class="content">
            <div style="display:grid">
                <h3>Test Setup:</h3>
                <ul>
                    <li>GTest Executable : {{gtest}}</li>
                    <li>Test Filter      : {{test_filter}}</li>
                    <li>Working Directory: {{out_dir}}</li>
                    <li>Total #Tests     : {{total}}</li>
                </ul>
                <h3>Test Summary:</h3>
                {{summary_table}}
            </div>
            <div style="margin-top: 50px">
                {{error_table}}
            </div>
        </div>
    </body>
    <footer><p>Report generated on {{datetime}}</p></footer>
</html>
"""


class FontColor(Enum):
    GREY = '\x1b[38;21m'
    BLUE = '\x1b[38;5;39m'
    YELLOW = '\x1b[38;5;226m'
    RED = '\x1b[38;5;196m'
    BOLD_RED = '\x1b[31;1m'
    RESET = '\x1b[0m'
    GREEN = '\x1b[38;5;46m'
    CYAN = '\x1b[38;5;51m'
    PURPLE = '\x1b[38;5;141m'
    DEFAULT = '\x1b[39m'


class SimpleLogger:
    def flush(self) -> None:
        """Flush print buffer"""
        print('', flush=True)

    def clear(self) -> None:
        """Clear terminal screen"""
        print(' ' * shutil.get_terminal_size().columns, end='\r', flush=True)

    def info(self, msg: str, fontcolor: FontColor = FontColor.DEFAULT) -> None:
        """Flush print log message"""
        if fontcolor != FontColor.DEFAULT:
            msg = f'{fontcolor.value}{msg}{FontColor.RESET.value}'
        print(msg, flush=True)

    def error(self, msg: str) -> None:
        """Flush print log message with red color"""
        print(f'{FontColor.RED.value}{msg}{FontColor.RESET.value}', flush=True)

    def warning(self, msg: str) -> None:
        """Flush print log message with yellow color"""
        print(f'{FontColor.YELLOW.value}{msg}{FontColor.RESET.value}', flush=True)

    def delay(self, msg: str, fontcolor: FontColor = FontColor.DEFAULT) -> None:
        """Allows print next message on the same line"""
        if fontcolor != FontColor.DEFAULT:
            msg = f'{fontcolor.value}{msg}{FontColor.RESET.value}'
        print(msg, end='', flush=True)

    def inline(self, msg: str, fontcolor: FontColor = FontColor.DEFAULT, final: bool = False) -> None:
        """Print log message on the same line by overwriting the previous message"""

        if fontcolor != FontColor.DEFAULT:
            msg = f'{fontcolor.value}{msg}{FontColor.RESET.value}'
        print(' ' * shutil.get_terminal_size().columns, end='\r', flush=True)
        print(msg, end='\r', flush=True)
        if final:
            print(' ' * shutil.get_terminal_size().columns, end='\r', flush=True)

    def center(self, msg: str, fontcolor: FontColor = FontColor.DEFAULT) -> None:
        """Print log message in the center of the terminal"""
        if fontcolor != FontColor.DEFAULT:
            msg = f'{fontcolor.value}{msg}{FontColor.RESET.value}'
        print(msg.center(shutil.get_terminal_size().columns), flush=True)


class GTestManager(SimpleLogger):
    INTERRUPT = threading.Event()
    LOCK = threading.Lock()

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.results = pd.DataFrame(columns=['Test', 'Status', 'Time', 'Log'])
        self.gtest = self._find_binary()
        self.options.output = self.options.output / f'{self.options.gtest}'  # _{datetime.now().strftime("%Y%m%d%H%M%S")}'
        self.options.output.mkdir(parents=True, exist_ok=True)

        # Private attributes
        self._tests = Queue()
        self._running_tests = Queue()
        self._total = 0
        self._finished = 0

    def _find_binary(self) -> Path:
        binary = f"{self.options.gtest}.exe" if ISWINDOWS else self.options.gtest
        paths = (self.options.root / 'builds').rglob(f'**/{binary}')

        valid_paths = [path for path in paths if 'simics' not in str(path)]
        if valid_paths:
            return valid_paths[0]

        self.error(f'GTest binary not found: {binary}')
        sys.exit(1)

    def __execute_cmd_with_output(self, cmd: str) -> str:
        try:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
            return output.decode('utf-8')
        except subprocess.CalledProcessError as e:
            self.error(f'Error executing command: {cmd}')
            self.error(e.output.decode('utf-8'))
            sys.exit(1)

    def __progress(self) -> None:
        if self._total == 0 or self.INTERRUPT.is_set():
            return
        progress = int((self._finished / self._total) * 100)
        pbar = '=' * (progress - 1) + '>' if progress > 0 else ''
        self.delay(f'\r[{pbar}{" " * (100 - progress)}] {progress}% ({self._finished}/{self._total})')

    def _run_test(self, test: tuple) -> None:
        test_name, cmd, working_dir, retry = test

        with self.LOCK:
            self._running_tests.put(test_name)

        working_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(working_dir)
        log = working_dir / 'run.log'
        start = time.time()
        ret = 0

        with open(log, 'w') as f:
            with subprocess.Popen(cmd, stdout=f, stderr=f, shell=True) as process:
                if self.INTERRUPT.is_set():
                    process.send_signal(signal.SIGINT)
                    ret = -signal.SIGINT
                else:
                    ret = process.wait()

        if ret != 0 and retry > 0 and not self.INTERRUPT.is_set():
            self._run_test((test_name, cmd, working_dir, retry - 1))
            return

        run_time = int(1000 * (time.time() - start))
        status = 'Passed' if ret == 0 else 'Killed' if ret == -signal.SIGINT else 'Failed'

        with self.LOCK:
            self._running_tests.get()
            self._finished += 1
            self.results.loc[len(self.results)] = [test_name, status, run_time, log]
            self.__progress()

    def _schedule_tests(self) -> None:
        running_groups = []
        test_group = None

        while True:
            if self.INTERRUPT.is_set():
                break

            if self._tests.empty():
                break

            test_candidate = None
            with self.LOCK:
                for _ in range(self._tests.qsize()):
                    test_candidate = self._tests.queue[0]
                    if test_candidate[0].split('.')[0] not in running_groups:
                        self._tests.get()
                        break

            if test_candidate is None:
                return

            test_group = test_candidate[0].split('.')[0]
            running_groups.append(test_group)
            self._run_test(test_candidate)

            if running_groups:
                running_groups.remove(test_group)

    def get_test_list(self) -> None:
        cmd = f'"{self.gtest}" --gtest_list_tests'

        if self.options.filter:
            cmd += f' --gtest_filter={self.options.filter}'

        test_list = self.__execute_cmd_with_output(cmd)
        current_group = None

        for line in test_list.splitlines():
            stripped_line = line.split('#')[0].strip()  # Remove comments and strip whitespace
            if not stripped_line:
                continue

            if line[0] != " ":
                current_group = stripped_line
            else:
                test_name = f'{current_group}{stripped_line}'
                test_cmd = f'"{self.gtest.as_posix()}" --gtest_filter={test_name}'

                if self.options.opts:
                    test_cmd += f' {" ".join(self.options.opts[1:])}'

                working_dir = self.options.output / test_name
                self._tests.put((test_name, test_cmd, working_dir, self.options.retry))

        self._total = self._tests.qsize()
        self.options.jobs = min(self.options.jobs, self._total)

    def execute_tests(self) -> None:
        self.info(f'Running {self._total} tests in {self.options.jobs} jobs...', FontColor.CYAN)
        self.__progress()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.options.jobs) as executor:
            futures = [executor.submit(self._schedule_tests) for _ in range(self.options.jobs)]

            try:
                while not all(f.done() for f in futures):
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self.INTERRUPT.set()
                self.warning('\n\nInterrupted by user...')
                executor.shutdown(wait=False, cancel_futures=True)

    def summerize(self) -> None:
        results = self.results.copy()
        results['Suite'] = results['Test'].apply(lambda x: x.split('.')[0].strip())

        summary = results.groupby('Suite').agg(
            Total=pd.NamedAgg(column='Test', aggfunc='count'),
            Passed=pd.NamedAgg(column='Status', aggfunc=lambda x: (x == 'Passed').sum()),
            Failed=pd.NamedAgg(column='Status', aggfunc=lambda x: (x == 'Failed').sum()),
            Killed=pd.NamedAgg(column='Status', aggfunc=lambda x: (x == 'Killed').sum()),
            Time=pd.NamedAgg(column='Time', aggfunc='sum')
        )

        summary['Time'] = summary['Time'] / 1000
        summary['Pass Rate'] = (summary['Passed'] / summary['Total'] * 100).round(2).fillna(0).astype(str) + '%'

        self.info('\n\nTest Summary:\n', FontColor.CYAN)
        self.info(summary.to_markdown())

        self.info('\n\nGenerating HTML Report...', FontColor.CYAN)
        self.generate_html_report(summary.reset_index(), results)

    def generate_html_report(self, summary: pd.DataFrame, results: pd.DataFrame) -> None:
        results = results.reset_index()
        status = results['Status'].unique().tolist()

        summary_table = summary.to_html(classes='report', index=False, escape=False, border=0)

        error_table = ''
        if 'Failed' in status or 'Killed' in status:
            error_table = results[results['Status'] != 'Passed'][['Suite', 'Test', 'Status', 'Time', 'Log']]
            error_table = [
                f"""\
                <tr>
                    <td>{row['Suite']}</td>
                    <td>{row['Test']}</td>
                    <td>{row['Status']}</td>
                    <td>{row['Time']}</td>
                    <td><a href="{row['Log']}" class="fa fa-file-text"></a></td>
                </tr>"""
                for _, row in error_table.iterrows()
            ]

            error_table = f"""\
                <table class="err">
                    <thead>
                        <tr>
                            <th>Suite</th>
                            <th>Test</th>
                            <th>Status</th>
                            <th>Run Time(ms)</th>
                            <th>Log</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(error_table)}
                    </tbody>
                </table>"""

        html_report = HTML_TEMPLATE.replace('{{title}}', f'{self.options.gtest} Report')
        html_report = html_report.replace('{{gtest}}', self.gtest.as_posix())
        html_report = html_report.replace('{{test_filter}}', self.options.filter)
        html_report = html_report.replace('{{out_dir}}', self.options.output.as_posix())
        html_report = html_report.replace('{{total}}', str(self._total))
        html_report = html_report.replace('{{error_table}}', error_table)
        html_report = html_report.replace('{{summary_table}}', summary_table)
        with open(self.options.output / 'report.html', 'w') as f:
            f.write(html_report)

        self.info(f"Test Report is generated at {self.options.output.as_posix()}/report.html", FontColor.CYAN)

    def run(self) -> None:
        self.get_test_list()

        self.flush()
        self.info('Setup:', FontColor.CYAN)
        self.info(f'  Root Directory  : {self.options.root}')
        self.info(f'  GTest Binary    : {self.gtest}')
        self.info(f'  Test Filter     : {self.options.filter}')
        self.info(f'  Output Directory: {self.options.output}')
        self.info(f'  Number of Tests : {self._total}')
        self.info(f'  Number of Jobs  : {self.options.jobs}')
        self.flush()

        start_time = datetime.now()
        self.execute_tests()
        self.summerize()
        elapsed_time = datetime.now() - start_time
        elapsed = time.strftime('%H:%M:%S', time.gmtime(elapsed_time.total_seconds()))
        self.info(f'\nTotal time taken: {elapsed}', FontColor.CYAN)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GTest Manager')
    parser.add_argument('-r', '--root', type=Path, default='.', help='Repo root directory')
    parser.add_argument('-g', '--gtest', type=str, help='GTest binary name without extension')
    parser.add_argument('-f', '--filter', type=str, default='*', help='Test filter. ex: "*Test*opt*"')
    parser.add_argument('-j', '--jobs', type=int, default=mp.cpu_count(), help='Number of jobs')
    parser.add_argument('-R', '--retry', type=int, default=2, help='Number of retry attempts')
    parser.add_argument('-t', '--timeout', type=int, default=60, help='Timeout in seconds')
    parser.add_argument('-o', '--output', type=Path, default=Path().cwd(), help='Output directory')
    parser.add_argument('opts', nargs=argparse.REMAINDER, help='Extra options. \
                                    Must be specified at end with -- separator')
    args = parser.parse_args()

    manager = GTestManager(args)
    manager.run()
