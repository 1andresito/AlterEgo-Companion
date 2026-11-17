"""The first-run setup: what is missing, and getting it with the user's consent.

A fresh install has no Ollama, no AI model and no voice files. Instead of
leaving the user to find out one error at a time, the setup window (see
setup_wizard.py) shows what is missing and asks. Nothing is downloaded unless
the user ticked it. This module holds the non-visual part:

    make_plan(config, synthesizer)  -> SetupPlan: what is there, what is missing
    SetupRunner.start(choices)      -> runs the chosen steps on a worker thread

    IDLE --start()--> RUNNING: OLLAMA -> MODEL -> VOICE --(worker done)--> IDLE

Each step reports through signals and a failing step does not stop the next
one: a broken download of the voice should not cost the user their AI model.
"""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QThread, Signal

from ..providers.base import ProviderError
from ..providers import ollama_install
from ..providers.ollama import DEFAULT_BASE_URL, OllamaProvider
from ..providers.ollama_server import DEFAULT_COMMAND, is_local, is_reachable, ollama_server
from ..settings.config import Config
from ..voice.synthesizer import Synthesizer


@dataclass(frozen=True)
class ModelChoice:
    name: str     # what Ollama calls it
    label: str    # shown in the setup
    size_gb: float


# All three can use tools (web search, files); the first is the default.
MODEL_CHOICES: tuple[ModelChoice, ...] = (
    ModelChoice("llama3.2", "Llama 3.2: good all-rounder (recommended)", 2.0),
    ModelChoice("llama3.2:1b", "Llama 3.2 1B: lighter, for small laptops", 1.3),
    ModelChoice("qwen2.5:7b", "Qwen 2.5 7B: smarter, needs 8 GB of free memory", 4.7),
)
DEFAULT_MODEL = MODEL_CHOICES[0].name
PERCENT = re.compile(r"(\d{1,3})%\s*$")


class SetupStep(Enum):
    OLLAMA = "ollama"
    MODEL = "model"
    VOICE = "voice"


STEP_LABELS = {
    SetupStep.OLLAMA: "Install Ollama",
    SetupStep.MODEL: "Download the AI model",
    SetupStep.VOICE: "Download my voice",
}


@dataclass
class SetupPlan:
    """What the setup found. Built on the GUI thread; every check is quick."""

    uses_ollama: bool                 # Ollama is the provider and runs on this computer
    ollama_installed: bool
    can_install_ollama: bool          # False on systems where only instructions can be given
    models: list[str] | None = None   # None: unknown, because the Ollama server is not running yet
    voice_needed: bool = False
    voice_size_mb: int = 0
    base_url: str = DEFAULT_BASE_URL
    command: str = DEFAULT_COMMAND

    @property
    def needs_ollama(self) -> bool:
        return self.uses_ollama and not self.ollama_installed

    @property
    def needs_model(self) -> bool:
        return self.uses_ollama and not self.models

    @property
    def anything_missing(self) -> bool:
        return self.needs_ollama or self.needs_model or self.voice_needed


@dataclass
class SetupChoices:
    """What the user ticked."""

    install_ollama: bool = False
    model: str = ""        # "" = no model now
    voice: bool = False

    def steps(self) -> list[SetupStep]:
        steps = []
        if self.install_ollama:
            steps.append(SetupStep.OLLAMA)
        if self.model:
            steps.append(SetupStep.MODEL)
        if self.voice:
            steps.append(SetupStep.VOICE)
        return steps


def make_plan(config: Config, synthesizer: Synthesizer | None) -> SetupPlan:
    base_url = str(config.get("ollama", "base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL)
    command = str(config.get("ollama", "command", DEFAULT_COMMAND) or DEFAULT_COMMAND)
    uses_ollama = config.provider == OllamaProvider.id and is_local(base_url)
    installed = ollama_install.is_installed(command)
    models: list[str] | None = None
    if uses_ollama and is_reachable(base_url, timeout=1.0):
        try:
            models = OllamaProvider(base_url, command, auto_start=False).list_models()
        except ProviderError:
            models = None
    voice_needed = bool(config.voice_enabled and synthesizer is not None and synthesizer.needs_download)
    return SetupPlan(
        uses_ollama=uses_ollama,
        ollama_installed=installed,
        can_install_ollama=ollama_install.can_install(),
        models=models,
        voice_needed=voice_needed,
        voice_size_mb=int(getattr(synthesizer, "download_size_mb", 0) or 0) if voice_needed else 0,
        base_url=base_url,
        command=command,
    )


def has_model(models: list[str], name: str) -> bool:
    """Ollama lists "llama3.2" as "llama3.2:latest"."""
    wanted = name if ":" in name else name + ":latest"
    return any(model == name or model == wanted for model in models)


class _SetupWorker(QThread):
    step_started = Signal(object)        # SetupStep
    progress = Signal(str, int)          # text, percent (-1 = unknown)
    step_done = Signal(object, str)      # SetupStep, what happened
    step_failed = Signal(object, str)    # SetupStep, the reason, for the user

    def __init__(self, plan: SetupPlan, choices: SetupChoices, synthesizer: Synthesizer | None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._plan = plan
        self._choices = choices
        self._synthesizer = synthesizer

    def run(self) -> None:
        for step in self._choices.steps():
            if self.isInterruptionRequested():
                return
            self.step_started.emit(step)
            try:
                self.step_done.emit(step, self._run_step(step))
            except ProviderError as error:
                self.step_failed.emit(step, str(error))
            except Exception as error:  # noqa: BLE001 - a library's unknown failure must not end the other steps
                traceback.print_exc()
                self.step_failed.emit(step, f"{type(error).__name__}: {error}")

    def _run_step(self, step: SetupStep) -> str:
        if step is SetupStep.OLLAMA:
            ollama_install.install(self.progress.emit, self._plan.command)
            return "Ollama is installed."
        if step is SetupStep.MODEL:
            return self._pull_model(self._choices.model)
        return self._download_voice()

    def _pull_model(self, model: str) -> str:
        plan = self._plan
        self.progress.emit("Checking Ollama...", -1)
        ollama_server.ensure_running(plan.base_url, plan.command, lambda text: self.progress.emit(text, -1))
        provider = OllamaProvider(plan.base_url, plan.command, auto_start=False)
        if has_model(provider.list_models(), model):
            return f"'{model}' was already there."

        def report(text: str) -> None:
            match = PERCENT.search(text)
            if text:
                self.progress.emit(text, int(match.group(1)) if match else -1)

        provider.pull(model, report)
        return f"'{model}' is downloaded."

    def _download_voice(self) -> str:
        synthesizer = self._synthesizer
        if synthesizer is None:
            raise ProviderError("There's no voice to download on this computer.")
        size = int(getattr(synthesizer, "download_size_mb", 0) or 0)
        self.progress.emit(f"Downloading my voice (about {size} MB)..." if size else "Downloading my voice...", -1)
        try:
            return synthesizer.prepare()
        except Exception as error:  # noqa: BLE001 - SynthesisError or whatever the voice library raises
            raise ProviderError(str(error)) from None


class SetupRunner(QObject):
    """Runs the chosen steps one after another, saving what they changed in the config."""

    step_started = Signal(object)
    progress = Signal(str, int)
    step_done = Signal(object, str)
    step_failed = Signal(object, str)
    finished = Signal()

    def __init__(self, config: Config, synthesizer: Synthesizer | None, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config
        self._synthesizer = synthesizer
        self._worker: _SetupWorker | None = None
        self._model = ""
        self.results: dict[SetupStep, tuple[bool, str]] = {}  # step -> (succeeded, what happened)

    @property
    def running(self) -> bool:
        return self._worker is not None

    def set_synthesizer(self, synthesizer: Synthesizer | None) -> None:
        """The voice can be rebuilt between two runs (a settings change); download the current one."""
        self._synthesizer = synthesizer

    def start(self, plan: SetupPlan, choices: SetupChoices) -> bool:
        if self._worker is not None:
            return False
        self.results = {}
        self._model = choices.model
        # No parent: if the runner goes away, the thread must not be destroyed with it while it ends.
        worker = _SetupWorker(plan, choices, self._synthesizer)
        worker.step_started.connect(self.step_started)
        worker.progress.connect(self.progress)
        # Bound methods, not lambdas: a lambda would run on the worker thread, these are queued to the GUI thread.
        worker.step_done.connect(self._on_done)
        worker.step_failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start(QThread.Priority.LowPriority)
        return True

    def wait(self, timeout_ms: int = 5000) -> None:
        """Used when quitting: ask the worker to stop after its current step and wait a little."""
        worker = self._worker
        if worker is not None:
            worker.requestInterruption()
            worker.wait(timeout_ms)

    # ----- GUI thread -----

    def _on_done(self, step: SetupStep, text: str) -> None:
        self.results[step] = (True, text)
        if step is SetupStep.MODEL:
            # The chosen model becomes the one Alter Ego thinks with.
            self._config.set("ollama", "model", self._model)
            self._config.set("ollama", "default_model", self._model)
            self._config.save()
        self.step_done.emit(step, text)

    def _on_failed(self, step: SetupStep, reason: str) -> None:
        print(f"Alter Ego: setup step '{step.value}' failed: {reason}")
        self.results[step] = (False, reason)
        self.step_failed.emit(step, reason)

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.finished.emit()
