"""Tool adapters: declarative TOML describing how a CLI fills roles.

An adapter says which CAO provider a tool maps to, whether CAO can enforce its
tool limits (native) or only ask nicely (soft), how to detect/authenticate it,
how to validate model IDs, and which roles it may fill.
"""

import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any, Protocol

# The four roles of the chain of command. Order is the display/render order.
ROLES = ("general", "engineer", "scout", "inspector")


class AdapterError(Exception):
    """Raised when an adapter is unknown or a tool cannot answer a query."""


class ProcessResult(Protocol):
    """The subset of ``subprocess.CompletedProcess`` that caokit reads.

    Declared structurally so tests can pass tiny fakes and production passes
    the real thing.

    Attributes:
        returncode: Process exit status.
        stdout: Captured standard output (text).
        stderr: Captured standard error (text).
    """

    returncode: int
    stdout: Any
    stderr: Any


# A runner executes an argv and returns its result. Injected so that no unit
# test needs a real CLI installed.
Runner = Callable[[Sequence[str]], ProcessResult]


def default_runner(argv: Sequence[str], timeout: int = 60) -> ProcessResult:
    """Run ``argv`` for real, capturing text output, with a timeout (60s by default).

    Args:
        argv: Command and arguments; never passed through a shell.
        timeout: Seconds to wait before giving up.

    Returns:
        The completed process with ``stdout``/``stderr`` as text.

    Raises:
        OSError: The binary does not exist or cannot be executed.
        subprocess.TimeoutExpired: The command ran longer than ``timeout`` seconds.
    """
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)


@dataclass
class RoleCap:
    """What one adapter can do for one role.

    Attributes:
        can_fill: False means the role is rejected for this tool.
        recommended_model: Advice only; users may override with a warning.
    """

    can_fill: bool  # False means the role is rejected for this tool
    recommended_model: str | None  # advice only; users may override with a warning


@dataclass
class Adapter:
    """Parsed contents of ``data/adapters/<tool>.toml``.

    Attributes:
        id: Tool identifier, equal to the TOML file stem (e.g. ``claude``).
        cao_provider: Value for the CAO profile's ``provider:`` field.
        enforcement: ``native`` (CAO denies tools) or ``soft`` (prompt-only).
        status: ``active`` or ``parked`` (parked tools cannot be selected).
        default_vendor: Vendor used when a model ID matches no prefix.
        binary: Executable name looked up on PATH.
        version_cmd: Command that prints the tool version.
        auth_cmd: Command that succeeds only when logged in; empty if none.
        models_source: ``cmd`` (ask the tool) or ``shape`` (regex/alias only).
        models_list_cmd: Command listing model IDs when ``models_source`` is ``cmd``.
        model_aliases: Accepted short model names for shape-validated tools.
        model_shape: Regex a model ID must match for shape-validated tools.
        vendor_map: Model-ID prefix to vendor; ``""`` is the catch-all.
        roles: Per-role capability and recommended model.
        frontmatter: Fixed extra frontmatter fields for rendered profiles.
        notes: Text appended to every rendered profile as "Tool notes".
    """

    id: str
    cao_provider: str  # value for the CAO profile's ``provider:`` field
    enforcement: str  # "native" (CAO denies tools) or "soft" (prompt-only)
    status: str  # "active" or "parked" (parked tools cannot be selected)
    default_vendor: str  # vendor used when a model ID matches no prefix
    binary: str
    version_cmd: list[str]
    auth_cmd: list[str]  # empty when the tool has no cheap non-interactive auth check
    models_source: str  # "cmd" = ask the tool, "shape" = regex/alias check only
    models_list_cmd: list[str]
    model_aliases: list[str]
    model_shape: str
    vendor_map: dict[str, str]  # model-ID prefix -> vendor; "" is the catch-all
    frontmatter: dict[str, str]  # fixed extra frontmatter fields for this tool
    roles: dict[str, RoleCap]
    notes: str = ""  # appended to every rendered profile as "Tool notes"


def adapter_ids() -> list[str]:
    """Return the IDs of every adapter shipped with the package.

    Returns:
        Sorted adapter IDs (TOML file stems), parked adapters included.
    """
    d = resources.files("caokit") / "data" / "adapters"
    return sorted(p.name[:-5] for p in d.iterdir() if p.name.endswith(".toml"))


def load_adapter(tool: str) -> Adapter:
    """Load the adapter for ``tool``.

    Args:
        tool: Adapter ID such as ``claude``; only ``[a-z0-9]+`` is accepted.

    Returns:
        The parsed adapter.

    Raises:
        AdapterError: ``tool`` is malformed or no such adapter ships.
    """
    # Restrict to [a-z0-9]+ so a tool name can never traverse out of data/adapters.
    if not re.fullmatch(r"[a-z0-9]+", tool or ""):
        raise AdapterError(f"unknown tool {tool!r}")
    p = resources.files("caokit") / "data" / "adapters" / (tool + ".toml")
    if not p.is_file():
        raise AdapterError(f"unknown tool {tool!r}")
    d = tomllib.loads(p.read_text(encoding="utf-8"))
    m = d.get("models", {})
    # Roles missing from the TOML default to "cannot fill", never to "can".
    roles = {
        r: RoleCap(
            can_fill=d.get("roles", {}).get(r, {}).get("can_fill", "no") == "yes",
            recommended_model=d.get("roles", {}).get(r, {}).get("recommended_model"),
        )
        for r in ROLES
    }
    return Adapter(
        id=d["id"],
        cao_provider=d["cao_provider"],
        enforcement=d["enforcement"],
        status=d["status"],
        default_vendor=d["default_vendor"],
        binary=d["detect"]["binary"],
        version_cmd=list(d["detect"]["version_cmd"]),
        auth_cmd=list(d["detect"].get("auth_cmd", [])),
        models_source=m.get("source", "shape"),
        models_list_cmd=list(m.get("list_cmd", [])),
        model_aliases=list(m.get("aliases", [])),
        model_shape=m.get("shape", ".*"),
        vendor_map=dict(m.get("vendor_map", {})),
        frontmatter=dict(d.get("frontmatter", {})),
        roles=roles,
        notes=d.get("notes", {}).get("text", ""),
    )


def vendor_of(adapter: Adapter, model: str | None) -> str:
    """Return the vendor of a model, e.g. ``claude-*`` on Antigravity is anthropic.

    This is what lets the cross-provider rule see that an Antigravity inspector
    running a Claude model is not independent of a Claude engineer.

    Args:
        adapter: The tool the model runs on.
        model: Model ID, or None for the tool's default.

    Returns:
        The vendor name, e.g. ``anthropic``; the adapter default if unmatched.
    """
    if model:
        # Longest prefix first, so a specific prefix beats a shorter one.
        for prefix, vendor in sorted(adapter.vendor_map.items(), key=lambda kv: -len(kv[0])):
            if prefix and model.startswith(prefix):
                return vendor
    return adapter.vendor_map.get("", adapter.default_vendor)


def list_models(adapter: Adapter, runner: Runner = default_runner) -> list[str]:
    """Return the model IDs the tool reports.

    Args:
        adapter: The tool to query.
        runner: Executes the list command; injected for tests.

    Returns:
        Model IDs, or an empty list for tools validated by shape only.

    Raises:
        AdapterError: The tool cannot be run, is not logged in, or listed nothing.
    """
    if adapter.models_source != "cmd":
        return []  # shape-validated tools have no list to fetch
    cmd = " ".join(adapter.models_list_cmd)
    try:
        r = runner(adapter.models_list_cmd)
    except (OSError, subprocess.SubprocessError) as e:
        raise AdapterError(f"cannot run {cmd}: {e}") from e
    if r.returncode != 0:
        detail = (r.stderr or r.stdout).strip()[:200]
        raise AdapterError(f"`{cmd}` failed (logged in?): {detail}")
    ids = []
    for line in r.stdout.splitlines():
        first = line.split("\t")[0].strip()  # `agy models` prints "<id>\t<label>"
        # Keep only ID-shaped tokens; this drops banners like "Fetching available models...".
        if first and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", first):
            ids.append(first)
    if not ids:
        raise AdapterError(f"`{cmd}` listed no models")
    return ids


def validate_model(
    adapter: Adapter, model: str, runner: Runner = default_runner
) -> tuple[list[str], list[str]]:
    """Check a model ID against the tool; return ``(errors, warnings)``.

    Tools that can list models reject unlisted IDs (errors). Tools that cannot
    (Claude) only warn when the ID is not a known alias or ``claude-*`` shape.

    Args:
        adapter: The tool the model is for.
        model: Model ID to check.
        runner: Executes the list command; injected for tests.

    Returns:
        A ``(errors, warnings)`` pair of message lists.
    """
    if adapter.models_source == "cmd":
        try:
            known = list_models(adapter, runner)
        except AdapterError as e:
            return [f"cannot validate model {model!r} for {adapter.id}: {e}"], []
        if model not in known:
            cmd = " ".join(adapter.models_list_cmd)
            return [f"model {model!r} is not listed by `{cmd}`"], []
        return [], []
    if model in adapter.model_aliases or re.fullmatch(adapter.model_shape, model):
        return [], []
    return [], [
        f"model {model!r} for {adapter.id} is not a known alias or claude-* ID; cannot verify it"
    ]
