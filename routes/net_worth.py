from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household
from models.balance_entry import BalanceEntries, BalanceEntry
from models.db import utcnow
from models.end_points.net_worth import (
    BalanceEntryCreateRequest,
    NetWorthItemCreateRequest,
    NetWorthItemsRequest,
    NetWorthItemUpdateRequest,
    NetWorthSummaryRequest,
)
from models.net_worth_item import NetWorthItem, NetWorthItems

net_worth_bp = Blueprint("net_worth", __name__)


def item_response(item: NetWorthItem, entries: list[BalanceEntry] = None):
    """Item dict with its current balance and full entry history attached."""
    if entries is None:
        entries = BalanceEntries.load_by_item_id(item.id).entries
    entries = sorted(
        entries, key=lambda e: (e.effective_date, e.id), reverse=True
    )
    latest = entries[0] if entries else None
    return {
        **item.model_dump(),
        "current_balance": latest.balance if latest else None,
        "current_balance_date": latest.effective_date if latest else None,
        "entries": [entry.model_dump() for entry in entries],
    }


@net_worth_bp.route("/items/", methods=["GET"])
@require_auth
def get_items():
    try:
        items_request = NetWorthItemsRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(items_request.household_id)
        if forbidden:
            return forbidden
        items = NetWorthItems.load_by_household_id(
            items_request.household_id
        )
        all_entries = BalanceEntries.load_by_item_ids(
            [item.id for item in items.items]
        ).entries
        entries_by_item: dict[int, list[BalanceEntry]] = {}
        for entry in all_entries:
            entries_by_item.setdefault(entry.item_id, []).append(entry)
        return jsonify(
            {
                "items": [
                    item_response(item, entries_by_item.get(item.id, []))
                    for item in items.items
                ]
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@net_worth_bp.route("/items/", methods=["POST"])
@require_auth
@block_demo_writes
def create_item():
    try:
        create_request = NetWorthItemCreateRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(create_request.household_id)
        if forbidden:
            return forbidden
        item = NetWorthItem(
            household_id=create_request.household_id,
            account_id=create_request.account_id,
            name=create_request.name.strip(),
            kind=create_request.kind,
            type=create_request.type.strip(),
            interest_rate=create_request.interest_rate,
            minimum_payment=create_request.minimum_payment,
        ).create()
        if not item:
            return (
                jsonify(
                    {
                        "message": "An item with that name already exists",
                        "status": 0,
                    }
                ),
                409,
            )
        if create_request.initial_balance is not None:
            entry = BalanceEntry(
                item_id=item.id,
                balance=create_request.initial_balance,
            )
            if create_request.balance_date:
                entry.effective_date = create_request.balance_date
            entry.create()
        return jsonify({"item": item_response(item)})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@net_worth_bp.route("/items/<int:item_id>", methods=["PUT"])
@require_auth
@block_demo_writes
def update_item(item_id):
    try:
        update_request = NetWorthItemUpdateRequest.model_validate_json(
            request.data
        )
        item = NetWorthItem.load(item_id)
        if not item:
            return jsonify({"message": "Item not found", "status": 0}), 404
        forbidden = require_household(item.household_id)
        if forbidden:
            return forbidden
        # exclude_unset so an explicit null clears a field (e.g. interest_rate)
        for field, value in update_request.model_dump(
            exclude_unset=True
        ).items():
            setattr(item, field, value)
        item.save()
        return jsonify({"item": item_response(item)})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@net_worth_bp.route("/items/<int:item_id>", methods=["DELETE"])
@require_auth
@block_demo_writes
def delete_item(item_id):
    item = NetWorthItem.load(item_id)
    if not item:
        return jsonify({"message": "Item not found", "status": 0}), 404
    forbidden = require_household(item.household_id)
    if forbidden:
        return forbidden
    # No DB cascade in DBModel — delete the entries explicitly first
    entries = BalanceEntries.load_by_item_id(item_id).entries
    for entry in entries:
        entry.delete()
    item.delete()
    return jsonify({"deleted": item_id, "deleted_entries": len(entries)})


@net_worth_bp.route("/items/<int:item_id>/balances/", methods=["POST"])
@require_auth
@block_demo_writes
def add_balance(item_id):
    try:
        entry_request = BalanceEntryCreateRequest.model_validate_json(
            request.data
        )
        item = NetWorthItem.load(item_id)
        if not item:
            return jsonify({"message": "Item not found", "status": 0}), 404
        forbidden = require_household(item.household_id)
        if forbidden:
            return forbidden
        entry = BalanceEntry(item_id=item_id, balance=entry_request.balance)
        if entry_request.effective_date:
            entry.effective_date = entry_request.effective_date
        entry.create()
        return jsonify({"entry": entry.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@net_worth_bp.route("/balances/<int:entry_id>", methods=["DELETE"])
@require_auth
@block_demo_writes
def delete_balance(entry_id):
    entry = BalanceEntry.load(entry_id)
    if not entry:
        return jsonify({"message": "Entry not found", "status": 0}), 404
    item = NetWorthItem.load(entry.item_id)
    forbidden = require_household(item.household_id) if item else (
        jsonify({"message": "Forbidden", "status": 0}), 403
    )
    if forbidden:
        return forbidden
    entry.delete()
    return jsonify({"deleted": entry_id})


@net_worth_bp.route("/summary/", methods=["GET"])
@require_auth
def get_summary():
    try:
        summary_request = NetWorthSummaryRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(summary_request.household_id)
        if forbidden:
            return forbidden
        series = NetWorthItems.net_worth_series(
            summary_request.household_id, summary_request.months
        )
        current = series[-1] if series else {"assets": 0, "debts": 0}
        return jsonify(
            {
                "total_assets": current["assets"],
                "total_debts": current["debts"],
                "net_worth": current["assets"] - current["debts"],
                "as_of": utcnow().isoformat(),
                "series": series,
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
