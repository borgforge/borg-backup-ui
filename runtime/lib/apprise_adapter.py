"""Provider-neutral adapter for the bundled Apprise runtime."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import signal
import sys
import threading
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator


logger = logging.getLogger(__name__)

RUNTIME_DIR = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR_DIR = RUNTIME_DIR / "vendor"


class AppriseAdapterError(RuntimeError):
    """Raised when the bundled Apprise runtime is unavailable or unusable."""


@dataclass(frozen=True)
class AppriseDeliveryResult:
    ok: bool
    message: str


def _safe_error(value: BaseException | str) -> str:
    text = str(value or "").strip()
    return text[:500] if text else "unknown error"


class _DiscoveryTimeoutError(TimeoutError):
    pass


@contextmanager
def _operation_timeout(seconds: int | float | None, label: str) -> Iterator[None]:
    if not seconds or seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _timeout_handler(signum: int, frame: object) -> None:
        raise _DiscoveryTimeoutError(f"{label} exceeded {seconds:g} seconds.")

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def load_bundled_apprise(
    *,
    vendor_dir: Path | str | None = None,
    apprise_module: ModuleType | Any | None = None,
) -> ModuleType | Any:
    """Load Apprise from runtime/vendor, never from host site-packages."""
    if apprise_module is not None:
        return apprise_module

    vendor = Path(vendor_dir) if vendor_dir is not None else DEFAULT_VENDOR_DIR
    if not vendor.is_dir():
        raise AppriseAdapterError(
            f"Bundled Apprise runtime is missing: {vendor}. Rebuild the plugin package."
        )

    spec = importlib.machinery.PathFinder.find_spec("apprise", [str(vendor)])
    if spec is None or spec.loader is None:
        raise AppriseAdapterError(
            f"Bundled Apprise module is not importable from {vendor}. Rebuild the plugin package."
        )

    vendor_text = str(vendor.resolve())
    existing = sys.modules.get("apprise")
    existing_file = Path(str(getattr(existing, "__file__", ""))).resolve() if existing else None
    if existing is not None and existing_file and _is_relative_to(existing_file, vendor.resolve()):
        return existing

    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules["apprise"] = module
        spec.loader.exec_module(module)
        module_file = Path(str(getattr(module, "__file__", ""))).resolve()
        if not _is_relative_to(module_file, vendor.resolve()):
            raise AppriseAdapterError(
                f"Bundled Apprise resolved outside runtime/vendor: {module_file}"
            )
        return module
    except AppriseAdapterError:
        if existing is not None:
            sys.modules["apprise"] = existing
        else:
            sys.modules.pop("apprise", None)
        raise
    except Exception as exc:  # noqa: BLE001 - adapter must expose clear diagnostics
        if existing is not None:
            sys.modules["apprise"] = existing
        else:
            sys.modules.pop("apprise", None)
        raise AppriseAdapterError(f"Bundled Apprise failed to load: {_safe_error(exc)}") from exc
    finally:
        # Keep runtime/vendor available after load; Apprise providers and their
        # dependencies can be imported lazily during validation or delivery.
        logger.debug("Apprise vendor path checked: %s", vendor_text)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def supported_providers(
    *,
    vendor_dir: Path | str | None = None,
    apprise_module: ModuleType | Any | None = None,
    timeout_seconds: int | float | None = 5,
) -> dict[str, Any]:
    """Return provider metadata exposed by the bundled Apprise version."""
    module = load_bundled_apprise(vendor_dir=vendor_dir, apprise_module=apprise_module)
    try:
        with _operation_timeout(timeout_seconds, "Apprise provider discovery"):
            details = module.Apprise().details()
    except _DiscoveryTimeoutError as exc:
        raise AppriseAdapterError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise AppriseAdapterError(f"Apprise provider discovery failed: {_safe_error(exc)}") from exc

    schemas = details.get("schemas") if isinstance(details, dict) else []
    providers = []
    for row in schemas if isinstance(schemas, list) else []:
        if not isinstance(row, dict):
            continue
        providers.append(
            {
                "service_name": str(row.get("service_name") or "").strip(),
                "service_url": str(row.get("service_url") or "").strip(),
                "setup_url": str(row.get("setup_url") or "").strip(),
                "schemas": _schema_values(row),
                "templates": _template_values(row),
                "tokens": _token_summaries(row),
            }
        )
    providers.sort(key=lambda item: (item["service_name"].lower(), item["schemas"]))
    return {
        "version": str(details.get("version") or getattr(module, "__version__", "") or ""),
        "providers": providers,
        "provider_count": len(providers),
    }


def _schema_values(row: dict[str, Any]) -> list[str]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    tokens = details.get("tokens") if isinstance(details.get("tokens"), dict) else {}
    schema = tokens.get("schema") if isinstance(tokens.get("schema"), dict) else {}
    values = schema.get("values")
    if isinstance(values, (list, tuple, set, frozenset)):
        return sorted(str(item) for item in values if str(item).strip())
    value = str(values or "").strip()
    return [value] if value else []


def _template_values(row: dict[str, Any]) -> list[str]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    values = details.get("templates") if isinstance(details.get("templates"), (list, tuple, set, frozenset)) else []
    out = []
    for value in values:
        text = str(value or "").strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _token_summaries(row: dict[str, Any]) -> list[dict[str, Any]]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    tokens = details.get("tokens") if isinstance(details.get("tokens"), dict) else {}
    out = []
    for key, value in sorted(tokens.items()):
        if key == "schema" or not isinstance(value, dict):
            continue
        name = str(value.get("name") or key).strip()
        token_type = str(value.get("type") or "").strip()
        required = bool(value.get("required"))
        private = bool(value.get("private"))
        prefix = str(value.get("prefix") or "").strip()
        item = {
            "key": str(key),
            "name": name,
            "type": token_type,
            "required": required,
            "private": private,
        }
        if prefix:
            item["prefix"] = prefix
        out.append(item)
    return out


def validate_url(
    url: str,
    *,
    vendor_dir: Path | str | None = None,
    apprise_module: ModuleType | Any | None = None,
) -> AppriseDeliveryResult:
    """Validate a generic Apprise URL without sending a notification."""
    text = str(url or "").strip()
    if not text:
        return AppriseDeliveryResult(False, "Apprise URL is empty.")
    module = load_bundled_apprise(vendor_dir=vendor_dir, apprise_module=apprise_module)
    try:
        app = module.Apprise()
        if not bool(app.add(text)):
            return AppriseDeliveryResult(False, "Apprise URL was rejected by the bundled runtime.")
    except Exception as exc:  # noqa: BLE001
        return AppriseDeliveryResult(False, f"Apprise URL validation failed: {_safe_error(exc)}")
    return AppriseDeliveryResult(True, "Apprise URL is valid.")


def send_test_notification(
    url: str,
    *,
    title: str = "Borg Backup UI",
    body: str = "This is a test notification from Borg Backup UI.",
    vendor_dir: Path | str | None = None,
    apprise_module: ModuleType | Any | None = None,
) -> AppriseDeliveryResult:
    """Send one test notification through a generic Apprise URL."""
    text = str(url or "").strip()
    validation = validate_url(text, vendor_dir=vendor_dir, apprise_module=apprise_module)
    if not validation.ok:
        return validation
    module = load_bundled_apprise(vendor_dir=vendor_dir, apprise_module=apprise_module)
    try:
        app = module.Apprise()
        app.add(text)
        ok = bool(app.notify(title=str(title or "Borg Backup UI"), body=str(body or "")))
    except Exception as exc:  # noqa: BLE001
        return AppriseDeliveryResult(False, f"Apprise test notification failed: {_safe_error(exc)}")
    return AppriseDeliveryResult(
        ok,
        "Apprise test notification sent." if ok else "Apprise test notification was not delivered.",
    )
