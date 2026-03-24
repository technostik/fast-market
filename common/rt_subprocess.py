import subprocess
import sys
import threading
from typing import Optional, List

class rt_subprocess:
    """
    A drop-in replacement for subprocess module with real-time capture
    """

    @staticmethod
    def run(*args, capture_output=True, text=True, **kwargs):
        """Same interface as subprocess.run"""
        return rt_subprocess._run_with_real_time(*args, capture_output=capture_output, text=text, **kwargs)

    @staticmethod
    def _run_with_real_time(*args, capture_output=True, text=True, **kwargs):
        """Internal method with real-time capture"""

        stdout_lines = []
        stderr_lines = []

        process = subprocess.Popen(
            *args,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=text,
            **kwargs
        )

        def read_stream(stream, lines_list, output_stream=None):
            if stream:
                for line in iter(stream.readline, ''):
                    if line:
                        lines_list.append(line)
                        if output_stream:
                            output_stream.write(line)
                            output_stream.flush()

        threads = []

        if capture_output:
            # Thread for stdout
            stdout_thread = threading.Thread(
                target=read_stream,
                args=(process.stdout, stdout_lines, sys.stdout)
            )
            stdout_thread.start()
            threads.append(stdout_thread)

            # Thread for stderr
            stderr_thread = threading.Thread(
                target=read_stream,
                args=(process.stderr, stderr_lines, sys.stderr)
            )
            stderr_thread.start()
            threads.append(stderr_thread)

        returncode = process.wait()

        # Wait for threads to finish
        for thread in threads:
            thread.join()

        return subprocess.CompletedProcess(
            args=process.args,
            returncode=returncode,
            stdout=''.join(stdout_lines) if capture_output else None,
            stderr=''.join(stderr_lines) if capture_output else None,
        )

    # Add other subprocess attributes if needed
    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired

