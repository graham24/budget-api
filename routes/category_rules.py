from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household
from models.category_rule import CategoryRule, CategoryRules
from models.end_points.category_rule import (
    CategoryRuleCreateRequest,
    CategoryRulesRequest,
)

category_rules_bp = Blueprint("category_rules", __name__)


@category_rules_bp.route("/", methods=["GET"])
@require_auth
def get_category_rules():
    try:
        rules_request = CategoryRulesRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(rules_request.household_id)
        if forbidden:
            return forbidden
        rules = CategoryRules.load_by_household_id(rules_request.household_id)
        return jsonify({"rules": [rule.model_dump() for rule in rules.rules]})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@category_rules_bp.route("/", methods=["POST"])
@require_auth
@block_demo_writes
def create_category_rule():
    try:
        rule_request = CategoryRuleCreateRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(rule_request.household_id)
        if forbidden:
            return forbidden
        rule = CategoryRule(
            household_id=rule_request.household_id,
            match_text=rule_request.match_text.strip(),
            category=rule_request.category.strip(),
            sub_category=rule_request.sub_category.strip(),
            need=rule_request.need,
            income=rule_request.income,
        ).create()
        if not rule:
            return (
                jsonify(
                    {
                        "message": "A rule with that match text already exists",
                        "status": 0,
                    }
                ),
                409,
            )
        return jsonify({"rule": rule.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@category_rules_bp.route("/<int:rule_id>", methods=["DELETE"])
@require_auth
@block_demo_writes
def delete_category_rule(rule_id):
    rule = CategoryRule.load(rule_id)
    if not rule:
        return jsonify({"message": "Rule not found", "status": 0}), 404
    forbidden = require_household(rule.household_id)
    if forbidden:
        return forbidden
    rule.delete()
    return jsonify({"deleted": rule_id})
