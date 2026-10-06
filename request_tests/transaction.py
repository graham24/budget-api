import json
import requests

host = "http://localhost:5000"
path = "api/transactions"
headers = {"Content-Type": "application/json"}
data = {
    "household_id": 1,
    "user_id": 1,
    # "from_date": "2025-01-01",
    # "to_date": "2025-02-01",
    # "type": "expenses-income",  #  transfers or expenses-income
}
# request = requests.get(f"{host}/{path}", json=data, headers=headers)
# request.raise_for_status()
# response = request.json()
# transactions = response.get("transactions")
# print(len(response.get("transactions")))

# for transaction in transactions:
#     print(
#         f"{transaction.get('date')}, {transaction.get('category')}, {transaction.get('sub_category')}, {transaction.get('amount')}"
#     )

path = "api/transactions/summary"
request = requests.get(
    f"{host}/{path}", params=data, headers=headers
)
request.raise_for_status()
response = request.json()
print(json.dumps(response))
net_income = response.get("net_income")
print(net_income)
for month in net_income:
    print(month)