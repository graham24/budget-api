from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask_cors import CORS
from routes.transactions import transactions_bp
from routes.household import household_bp
from routes.accounts import accounts_bp
from routes.users import users_bp
from routes.auth import auth_bp
from routes.budget_analysis import budget_analysis_bp
from routes.category_rules import category_rules_bp
from routes.budget_targets import budget_targets_bp
from routes.net_worth import net_worth_bp
from routes.simplefin import simplefin_bp
from routes.import_errors import import_errors_bp
from routes.billing import billing_bp

app = Flask(__name__)
CORS(app, origins=[
    "http://localhost:5173",
])


# Register Blueprints
app.register_blueprint(transactions_bp, url_prefix="/api/transactions")
app.register_blueprint(household_bp, url_prefix="/api/household")
app.register_blueprint(accounts_bp, url_prefix="/api/accounts")
app.register_blueprint(users_bp, url_prefix="/api/users")
app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(budget_analysis_bp, url_prefix="/api/budget-analysis")
app.register_blueprint(category_rules_bp, url_prefix="/api/category-rules")
app.register_blueprint(budget_targets_bp, url_prefix="/api/budget-targets")
app.register_blueprint(net_worth_bp, url_prefix="/api/net-worth")
app.register_blueprint(simplefin_bp, url_prefix="/api/simplefin")
app.register_blueprint(import_errors_bp, url_prefix="/api/import-errors")
app.register_blueprint(billing_bp, url_prefix="/api/billing")
print(app.url_map)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
