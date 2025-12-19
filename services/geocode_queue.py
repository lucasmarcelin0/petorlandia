import threading
import time
from typing import Any

from flask import current_app
from sqlalchemy import or_

from extensions import db
from helpers import geocode_address
from models import Endereco


class AddressGeocodeQueue:
    """Background worker that geocodes addresses without blocking requests."""

    def __init__(self, app):
        self._app = app
        self._lock = threading.Lock()
        self._running = False
        self._stats: dict[str, Any] = {
            "total": 0,
            "processed": 0,
            "updated": 0,
            "skipped": 0,
        }

    def start(self) -> bool:
        """Start the worker if it's not already running."""

        with self._lock:
            if self._running:
                return False
            self._running = True
            thread = threading.Thread(
                target=self._run,
                name="address-geocode-queue",
                daemon=True,
            )
            thread.start()
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                **self._stats,
            }

    def _run(self) -> None:
        try:
            with self._app.app_context():
                addresses = (
                    Endereco.query.filter(
                        or_(Endereco.latitude.is_(None), Endereco.longitude.is_(None))
                    )
                    .order_by(Endereco.id)
                    .all()
                )
                with self._lock:
                    self._stats = {
                        "total": len(addresses),
                        "processed": 0,
                        "updated": 0,
                        "skipped": 0,
                    }

                for endereco in addresses:
                    coords = geocode_address(
                        cep=endereco.cep,
                        rua=endereco.rua,
                        numero=endereco.numero,
                        bairro=endereco.bairro,
                        cidade=endereco.cidade,
                        estado=endereco.estado,
                    )

                    if coords:
                        endereco.latitude, endereco.longitude = coords
                        db.session.add(endereco)
                        db.session.commit()
                        self._increment("updated")
                    else:
                        self._increment("skipped")

                    self._increment("processed")
                    time.sleep(1)
        except Exception as exc:  # pragma: no cover - defensive guard in background thread
            with self._app.app_context():
                current_app.logger.exception("Erro na fila de geocodificação: %s", exc)
        finally:
            with self._lock:
                self._running = False

    def _increment(self, key: str) -> None:
        with self._lock:
            if key not in self._stats:
                return
            self._stats[key] += 1

