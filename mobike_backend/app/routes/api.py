from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, Optional

from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from ..auth import admin_required, auth_required, authenticate_user, register_user
from ..storage import JsonFileStorage, _utc_ts


def _get_base_url() -> str:
    """
    Return configured backend base URL that frontend can use.

    Env:
      - MOBIKE_BASE_URL (example: http://localhost:3001)
    """
    return os.environ.get("MOBIKE_BASE_URL", "http://localhost:3001")


def _json_error(message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
    payload: Dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    return payload, status_code


def _public_bike(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": b["id"],
        "name": b.get("name"),
        "model": b.get("model"),
        "location": b.get("location"),
        "rate_per_hour": b.get("rate_per_hour"),
        "is_available": bool(b.get("is_available", False)),
        "created_at": b.get("created_at"),
        "updated_at": b.get("updated_at"),
    }


def _public_rental(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "user_id": r.get("user_id"),
        "bike_id": r.get("bike_id"),
        "start_time": r.get("start_time"),
        "end_time": r.get("end_time"),
        "status": r.get("status"),
        "total_cost": r.get("total_cost"),
    }


storage = JsonFileStorage()

blp = Blueprint(
    "Mobike API",
    "mobike_api",
    url_prefix="/api",
    description="Mobike bike rental REST API (auth, bikes, rentals, admin).",
)


class RegisterSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(min=6, max=128))


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(min=1, max=128))


class BikeCreateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    model = fields.String(required=True, validate=validate.Length(min=1, max=80))
    location = fields.String(required=True, validate=validate.Length(min=1, max=120))
    rate_per_hour = fields.Float(required=True, validate=validate.Range(min=0))
    is_available = fields.Boolean(required=False, load_default=True)


class BikeUpdateSchema(Schema):
    name = fields.String(required=False, validate=validate.Length(min=1, max=80))
    model = fields.String(required=False, validate=validate.Length(min=1, max=80))
    location = fields.String(required=False, validate=validate.Length(min=1, max=120))
    rate_per_hour = fields.Float(required=False, validate=validate.Range(min=0))
    is_available = fields.Boolean(required=False)


class RentalCreateSchema(Schema):
    bike_id = fields.Integer(required=True)


@blp.route("/meta")
class MetaRoute(MethodView):
    def get(self):
        """Return API metadata helpful for frontend integration."""
        return {
            "base_url": _get_base_url(),
            "server_time": int(time.time()),
            "message": "Mobike backend API",
        }


@blp.route("/auth/register")
class RegisterRoute(MethodView):
    @blp.arguments(RegisterSchema)
    def post(self, payload):
        """Register a new user and return JWT token."""
        try:
            user, token = register_user(
                storage=storage,
                name=payload["name"],
                email=payload["email"],
                password=payload["password"],
            )
            return {"user": user, "token": token}, 201
        except ValueError as e:
            return _json_error(str(e), 400)


@blp.route("/auth/login")
class LoginRoute(MethodView):
    @blp.arguments(LoginSchema)
    def post(self, payload):
        """Login with email/password and return JWT token."""
        try:
            user, token = authenticate_user(
                storage=storage,
                email=payload["email"],
                password=payload["password"],
            )
            return {"user": user, "token": token}
        except ValueError as e:
            return _json_error(str(e), 401)


@blp.route("/bikes")
class BikesRoute(MethodView):
    def get(self):
        """
        List bikes.

        Query params:
          - available=true|false (optional)
        """
        available_param = request.args.get("available")
        filters: Dict[str, Any] = {}
        if available_param is not None:
            filters["is_available"] = available_param.strip().lower() in ("1", "true", "yes", "y")

        bikes = storage.list("bikes", **filters)
        bikes_sorted = sorted(bikes, key=lambda x: int(x["id"]))
        return {"bikes": [_public_bike(b) for b in bikes_sorted]}


@blp.route("/bikes/<int:bike_id>")
class BikeByIdRoute(MethodView):
    def get(self, bike_id: int):
        """Get bike details."""
        bike = storage.find_one("bikes", id=bike_id)
        if bike is None:
            return _json_error("Bike not found", 404)
        return {"bike": _public_bike(bike)}


@blp.route("/rentals")
class RentalsRoute(MethodView):
    @auth_required(storage)
    def get(self, current_user, *args, **kwargs):
        """List current user's rentals (active + history)."""
        rentals = storage.list("rentals", user_id=current_user["id"])
        rentals_sorted = sorted(rentals, key=lambda x: int(x["id"]), reverse=True)
        return {"rentals": [_public_rental(r) for r in rentals_sorted]}

    @auth_required(storage)
    @blp.arguments(RentalCreateSchema)
    def post(self, current_user, payload):
        """Create a rental booking for an available bike."""
        bike_id = int(payload["bike_id"])
        data = storage.get_all()
        bike = next((b for b in data.get("bikes", []) if int(b.get("id")) == bike_id), None)
        if bike is None:
            return _json_error("Bike not found", 404)
        if not bool(bike.get("is_available", False)):
            return _json_error("Bike is not available", 409)

        # Ensure user doesn't have an active rental for same bike
        for r in data.get("rentals", []):
            if int(r.get("user_id")) == int(current_user["id"]) and r.get("status") == "ACTIVE":
                return _json_error("You already have an active rental. Return it before booking another.", 409)

        rental_id = storage.next_id("rentals")
        now = _utc_ts()
        rental = {
            "id": rental_id,
            "user_id": current_user["id"],
            "bike_id": bike_id,
            "start_time": now,
            "end_time": None,
            "status": "ACTIVE",
            "total_cost": None,
        }
        data["rentals"].append(rental)

        # mark bike unavailable
        bike["is_available"] = False
        bike["updated_at"] = now

        storage.update_all(data)
        return {"rental": _public_rental(rental)}, 201


@blp.route("/rentals/<int:rental_id>/return")
class RentalReturnRoute(MethodView):
    @auth_required(storage)
    def post(self, current_user, rental_id: int):
        """End a rental (return bike) and compute total cost (hourly)."""
        data = storage.get_all()
        rental = next((r for r in data.get("rentals", []) if int(r.get("id")) == rental_id), None)
        if rental is None:
            return _json_error("Rental not found", 404)
        if int(rental.get("user_id")) != int(current_user["id"]):
            return _json_error("Not allowed", 403)
        if rental.get("status") != "ACTIVE":
            return _json_error("Rental is not active", 409)

        bike = next((b for b in data.get("bikes", []) if int(b.get("id")) == int(rental.get("bike_id"))), None)
        if bike is None:
            return _json_error("Bike not found for this rental", 500)

        end_time = _utc_ts()
        start_time = int(rental.get("start_time") or end_time)
        duration_seconds = max(0, end_time - start_time)
        hours = max(1, math.ceil(duration_seconds / 3600.0))  # charge minimum 1 hour
        rate = float(bike.get("rate_per_hour") or 0.0)
        total_cost = round(hours * rate, 2)

        rental["end_time"] = end_time
        rental["status"] = "COMPLETED"
        rental["total_cost"] = total_cost

        # Mark bike available again
        bike["is_available"] = True
        bike["updated_at"] = end_time

        storage.update_all(data)
        return {"rental": _public_rental(rental), "billing": {"hours": hours, "rate_per_hour": rate, "total_cost": total_cost}}


# ----------------- Admin endpoints -----------------

@blp.route("/admin/bikes")
class AdminBikesRoute(MethodView):
    @admin_required(storage)
    def get(self, current_user, *args, **kwargs):
        """Admin: list all bikes."""
        bikes = storage.list("bikes")
        bikes_sorted = sorted(bikes, key=lambda x: int(x["id"]))
        return {"bikes": [_public_bike(b) for b in bikes_sorted]}

    @admin_required(storage)
    @blp.arguments(BikeCreateSchema)
    def post(self, current_user, payload):
        """Admin: add a bike."""
        data = storage.get_all()
        bike_id = storage.next_id("bikes")
        now = _utc_ts()
        bike = {
            "id": bike_id,
            "name": payload["name"],
            "model": payload["model"],
            "location": payload["location"],
            "rate_per_hour": float(payload["rate_per_hour"]),
            "is_available": bool(payload.get("is_available", True)),
            "created_at": now,
            "updated_at": now,
        }
        data["bikes"].append(bike)
        storage.update_all(data)
        return {"bike": _public_bike(bike)}, 201


@blp.route("/admin/bikes/<int:bike_id>")
class AdminBikeByIdRoute(MethodView):
    @admin_required(storage)
    @blp.arguments(BikeUpdateSchema)
    def put(self, current_user, payload, bike_id: int):
        """Admin: update a bike."""
        data = storage.get_all()
        bike = next((b for b in data.get("bikes", []) if int(b.get("id")) == bike_id), None)
        if bike is None:
            return _json_error("Bike not found", 404)

        now = _utc_ts()
        for key in ("name", "model", "location", "rate_per_hour", "is_available"):
            if key in payload:
                bike[key] = payload[key]
        bike["updated_at"] = now

        storage.update_all(data)
        return {"bike": _public_bike(bike)}
