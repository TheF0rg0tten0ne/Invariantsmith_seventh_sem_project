"""
Local code execution for the "Run" button.

This never talks to the server. Fix-suggestion and conversion go through
the model server because that's where the model lives; running code has
nothing to do with the model and everything to do with whatever
compilers/interpreters are already on THIS machine's PATH -- exactly the
same gcc/javac/python3 the rest of Invariantsmith already assumes you
have locally for the C/Java/Python workflows to make sense at all.

Compile-then-run is modeled as a queue of subprocess stages:
  python -> [python3 main.py]
  c      -> [gcc main.c -o main, ./main]
  java   -> [javac Main.java, java -cp <tmp> Main]
A failing stage stops the queue (no point running a stale/nonexistent
binary after a failed compile). Only the LAST stage receives the user's
stdin -- feeding stdin to a compiler makes no sense.
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

RUN_TIMEOUT_S = 30  # safety net against an accidental infinite loop; user's own
                    # code, so this is a courtesy, not a security boundary


class CodeRunner(QObject):
    """One instance, reused across runs. Call run() again while something
    is still executing and it kills the previous run first -- only one
    run at a time makes sense for a single editor buffer."""

    started = Signal()
    outputReady = Signal(str)    # a chunk of combined stdout/stderr, already decoded
    finished = Signal(int)       # exit code of whichever stage ran last
    failedToStart = Signal(str)  # human-readable reason, e.g. "gcc not found on PATH"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._queue: list[list[str]] = []
        self._cwd: str | None = None
        self._stdin_text = ""
        self._expected_kill = False
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

    def work_dir(self) -> str | None:
        """Temp directory of the current/last run (so the UI can show the
        user's file name instead of an ugly temp path in tracebacks)."""
        return self._cwd

    def is_running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def stop(self):
        self._timeout_timer.stop()
        if self._process is not None and self.is_running():
            self._expected_kill = True  # kill() below will fire errorOccurred(Crashed); _on_error checks this
            self._process.kill()
            self._process.waitForFinished(2000)
        self._cleanup_tmpdir()

    def run(self, language: str, code: str, stdin_text: str = ""):
        self.stop()  # never let two runs overlap
        self._expected_kill = False
        self._tmpdir = tempfile.TemporaryDirectory(prefix="invariantsmith_run_")
        tmp = Path(self._tmpdir.name)
        self._cwd = str(tmp)
        self._stdin_text = stdin_text

        if language == "python":
            # Prefer the interpreter this app itself runs on: it always exists,
            # and on Windows a bare `python3` on PATH is often the Microsoft
            # Store stub that opens the Store instead of running anything.
            exe = sys.executable or shutil.which("python3") or shutil.which("python")
            if not exe:
                self.failedToStart.emit("No 'python3' or 'python' found on PATH.")
                self._cleanup_tmpdir()
                return
            src = tmp / "main.py"
            src.write_text(code, encoding="utf-8")
            self._queue = [[exe, "-u", str(src)]]  # -u: unbuffered, so output streams live

        elif language == "c":
            gcc = shutil.which("gcc") or shutil.which("cc")
            if not gcc:
                self.failedToStart.emit("No 'gcc' or 'cc' found on PATH.")
                self._cleanup_tmpdir()
                return
            src = tmp / "main.c"
            src.write_text(code, encoding="utf-8")
            exe_path = tmp / ("main.exe" if os.name == "nt" else "main")
            self._queue = [
                [gcc, str(src), "-o", str(exe_path)],
                [str(exe_path)],
            ]

        elif language == "java":
            javac = shutil.which("javac")
            java = shutil.which("java")
            if not javac or not java:
                self.failedToStart.emit("No 'javac'/'java' found on PATH (JDK required).")
                self._cleanup_tmpdir()
                return
            # javac requires the source filename to match the public class
            # name -- scan for it rather than assuming "Main", since a
            # pasted snippet can declare any class name.
            m = re.search(r"\bpublic\s+class\s+(\w+)", code)
            class_name = m.group(1) if m else "Main"
            src = tmp / f"{class_name}.java"
            src.write_text(code, encoding="utf-8")
            self._queue = [
                [javac, str(src)],
                [java, "-cp", str(tmp), class_name],
            ]

        else:
            self.failedToStart.emit(f"Don't know how to run language '{language}'.")
            self._cleanup_tmpdir()
            return

        self._run_next_stage()

    def _run_next_stage(self):
        argv = self._queue.pop(0)
        is_last_stage = not self._queue  # the actual run, not a compile step

        proc = QProcess(self)
        proc.setWorkingDirectory(self._cwd)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self._on_ready_read(proc))
        proc.finished.connect(self._on_stage_finished)
        proc.errorOccurred.connect(self._on_error)
        self._process = proc

        self.started.emit()
        proc.start(argv[0], argv[1:])
        if not proc.waitForStarted(3000):
            self.failedToStart.emit(f"Failed to start: {' '.join(argv)}")
            self._cleanup_tmpdir()
            return

        if is_last_stage:
            if self._stdin_text:
                proc.write(self._stdin_text.encode("utf-8"))
            self._timeout_timer.start(RUN_TIMEOUT_S * 1000)
        proc.closeWriteChannel()

    def _on_ready_read(self, proc):
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.outputReady.emit(data)

    def _on_stage_finished(self, exit_code, exit_status):
        self._timeout_timer.stop()
        if self._process is None:
            return  # already concluded via _on_error for this run
        was_last_stage = not self._queue  # queue already had this stage popped before it ran
        if exit_code != 0 or was_last_stage:
            self.finished.emit(exit_code)
            self._cleanup_tmpdir()
            return
        self._run_next_stage()

    def _on_timeout(self):
        self.outputReady.emit(f"\n[Killed: exceeded {RUN_TIMEOUT_S}s -- possible infinite loop]\n")
        if self._process is not None:
            self._expected_kill = True
            self._process.kill()

    def _on_error(self, error):
        # errorOccurred can fire alongside a normal finished() for the
        # same process (e.g. a crash) -- _process is cleared here first,
        # so if finished() arrives afterward, _on_stage_finished's guard
        # above skips it instead of emitting a second finished/cleanup.
        if self._process is not None:
            self._timeout_timer.stop()
            if not self._expected_kill:
                self.failedToStart.emit(f"Process error (code {error})")
            self._cleanup_tmpdir()

    def _cleanup_tmpdir(self):
        self._process = None
        if self._tmpdir is not None:
            try:
                self._tmpdir.cleanup()
            except Exception:
                pass
            self._tmpdir = None
