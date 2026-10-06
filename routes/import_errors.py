from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household
from models.import_error import ImportErrorLog, ImportErrorLogs
from models.end_points.import_error import ImportErrorsRequest

import_errors_bp = Blueprint("import_errors", __name__)


@import_errors_bp.route("/", methods=["GET"])
@require_auth
def get_import_errors():
    try:
        errors_request = ImportErrorsRequest.model_validate(request.args.to_dict())
        forbidden = require_household(errors_request.household_id)
        if forbidden:
            return forbidden
        errors = ImportErrorLogs.load_by_household_id(errors_request.household_id)
        return jsonify({"errors": [error.model_dump() for error in errors.errors]})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@import_errors_bp.route("/<int:error_id>", methods=["DELETE"])
@require_auth
@block_demo_writes
def delete_import_error(error_id):
    error = ImportErrorLog.load(error_id)
    if not error:
        return jsonify({"message": "Error not found", "status": 0}), 404
    forbidden = require_household(error.household_id)
    if forbidden:
        return forbidden
    error.delete()
    return jsonify({"deleted": error_id})
