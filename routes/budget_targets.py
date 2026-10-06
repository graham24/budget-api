from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household
from models.budget_target import BudgetTarget, BudgetTargets
from models.end_points.budget_target import (
    BudgetTargetSaveRequest,
    BudgetTargetsRequest,
)

budget_targets_bp = Blueprint("budget_targets", __name__)


@budget_targets_bp.route("/", methods=["GET"])
@require_auth
def get_budget_targets():
    try:
        targets_request = BudgetTargetsRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(targets_request.household_id)
        if forbidden:
            return forbidden
        targets = BudgetTargets.load_by_household_id(
            targets_request.household_id
        )
        return jsonify(
            {"targets": [target.model_dump() for target in targets.targets]}
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@budget_targets_bp.route("/", methods=["POST"])
@require_auth
@block_demo_writes
def save_budget_target():
    """Upsert: update the limit if a target already exists for the category."""
    try:
        save_request = BudgetTargetSaveRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(save_request.household_id)
        if forbidden:
            return forbidden
        target = BudgetTargets.load_by_category(
            household_id=save_request.household_id,
            category=save_request.category.strip(),
        )
        if target:
            target.monthly_limit = save_request.monthly_limit
            target.save()
        else:
            target = BudgetTarget(
                household_id=save_request.household_id,
                category=save_request.category.strip(),
                monthly_limit=save_request.monthly_limit,
            ).create()
        return jsonify({"target": target.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@budget_targets_bp.route("/<int:target_id>", methods=["DELETE"])
@require_auth
@block_demo_writes
def delete_budget_target(target_id):
    target = BudgetTarget.load(target_id)
    if not target:
        return jsonify({"message": "Target not found", "status": 0}), 404
    forbidden = require_household(target.household_id)
    if forbidden:
        return forbidden
    target.delete()
    return jsonify({"deleted": target_id})
