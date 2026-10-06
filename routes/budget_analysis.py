from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from analyze import BudgetAnalyzer
from auth_utils import block_demo_writes, require_auth, require_household
from models.budget_analysis import BudgetAnalysis, BudgetAnalyses
from models.budget_target import BudgetTargets
from models.end_points.budget_analysis import BudgetAnalysisRequest
from models.net_worth_item import NetWorthItems

budget_analysis_bp = Blueprint("budget_analysis", __name__)


@budget_analysis_bp.route("/", methods=["POST"])
@require_auth
@block_demo_writes
def generate_budget_analysis():
    """
    Generate a budget analysis for the last 3 complete months plus the
    current month to date using Claude, persist it, and return it.

    If an analysis already exists for the same date range and transaction count,
    the cached record is returned without calling the API.
    """
    try:
        analysis_request = BudgetAnalysisRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(analysis_request.household_id)
        if forbidden:
            return forbidden
        analyzer = BudgetAnalyzer(household_id=analysis_request.household_id)

        if analysis_request.from_date and analysis_request.to_date:
            from_date = analysis_request.from_date
            to_date = analysis_request.to_date
        else:
            from_date, to_date = analyzer.get_date_range()
        transaction_count = analyzer.count_transactions(from_date, to_date)

        existing = BudgetAnalysis.find_matching(
            household_id=analysis_request.household_id,
            from_date=from_date,
            to_date=to_date,
            transaction_count=transaction_count,
        )
        # Cache is stale if any budget target or net worth data changed
        # after it was generated
        if (
            not analysis_request.force
            and existing
            and not BudgetTargets.modified_since(
                analysis_request.household_id, existing.created
            )
            and not NetWorthItems.modified_since(
                analysis_request.household_id, existing.created
            )
        ):
            return jsonify({"analysis": existing.model_dump(), "cached": True})

        analysis_text, transaction_count = analyzer.generate_analysis(
            from_date, to_date
        )
        analysis = BudgetAnalysis(
            household_id=analysis_request.household_id,
            analysis=analysis_text,
            from_date=from_date,
            to_date=to_date,
            transaction_count=transaction_count,
        )
        analysis.create()

        return jsonify({"analysis": analysis.model_dump(), "cached": False})
    except ValidationError as e:
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
    except Exception as e:
        print(e)
        return (
            jsonify(
                {
                    "errors": str(e),
                    "message": "Error generating analysis",
                    "status": 0,
                }
            ),
            500,
        )


@budget_analysis_bp.route("/", methods=["GET"])
@require_auth
def get_budget_analysis():
    """
    Return the most recently generated budget analysis for a household.
    """
    try:
        analysis_request = BudgetAnalysisRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(analysis_request.household_id)
        if forbidden:
            return forbidden
        analyses = BudgetAnalyses.load_latest_by_household(
            analysis_request.household_id
        )

        if not analyses.analyses:
            return jsonify({"analysis": None}), 404

        return jsonify({"analysis": analyses.analyses[0].model_dump()})
    except ValidationError as e:
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
