from importers.importer import Importer
from models.account import Account
from models.user import User

user = User.load_by_email(email="you@example.com")
apple_account = Account.load(6)
filename = "import_files/Savings Transactions - February 2025.csv"
import_transactions = Importer.import_transactions(
    file=filename, account=apple_account
)
