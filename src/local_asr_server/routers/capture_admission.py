from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from local_asr_server.runtime.workload_arbiter import (
    CaptureReservationConflict,
    CaptureReservationNotFound,
    HeavyWorkloadArbiter,
    WorkloadArbiterClosed,
)


router = APIRouter()


def _arbiter(request: Request) -> HeavyWorkloadArbiter:
    return request.app.state.heavy_workload_arbiter


@router.post("/v1/capture/reservations", status_code=202)
def create_capture_reservation(request: Request) -> dict[str, object]:
    reservation_id = str(uuid.uuid4())
    try:
        return _arbiter(request).reserve_capture(reservation_id)
    except CaptureReservationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkloadArbiterClosed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/v1/capture/reservations/{reservation_id}")
def get_capture_reservation(reservation_id: str, request: Request) -> dict[str, object]:
    try:
        return _arbiter(request).capture_reservation(reservation_id)
    except CaptureReservationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/v1/capture/reservations/{reservation_id}", status_code=204)
def delete_capture_reservation(reservation_id: str, request: Request) -> Response:
    if not _arbiter(request).release_capture(reservation_id):
        raise HTTPException(status_code=404, detail="capture reservation is not active")
    return Response(status_code=204)


@router.post("/v1/capture/reservations/{reservation_id}/release", status_code=204)
def release_capture_reservation(reservation_id: str, request: Request) -> Response:
    """POST alias for lifecycle cleanup paths that cannot reliably send DELETE."""
    if not _arbiter(request).release_capture(reservation_id):
        raise HTTPException(status_code=404, detail="capture reservation is not active")
    return Response(status_code=204)
