import json
import os


def load_account(accounts_dir, account_id):
    path = os.path.join(accounts_dir, f"{account_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def list_accounts(accounts_dir, owner=""):
    accounts = []
    for filename in sorted(os.listdir(accounts_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(accounts_dir, filename), "r") as f:
            account = json.load(f)
        if owner and account.get("owner") != owner:
            continue
        accounts.append(account)
    return accounts


def save_account(accounts_dir, account_id, data):
    path = os.path.join(accounts_dir, f"{account_id}.json")
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def save_transaction(transactions_dir, tx_id, data):
    path = os.path.join(transactions_dir, f"{tx_id}.json")
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def list_transactions(transactions_dir, account_id=""):
    transactions = []
    for filename in sorted(os.listdir(transactions_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(transactions_dir, filename), "r") as f:
            tx = json.load(f)
        if account_id and account_id not in (tx.get("source_account"), tx.get("dest_account")):
            continue
        transactions.append(tx)
    transactions.sort(key=lambda tx: tx.get("timestamp", ""), reverse=True)
    return transactions


def save_pending(pending_dir, tx_id, data):
    path = os.path.join(pending_dir, f"{tx_id}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def remove_pending(pending_dir, tx_id):
    path = os.path.join(pending_dir, f"{tx_id}.json")
    if os.path.exists(path):
        os.remove(path)
