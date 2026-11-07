"""Accounts and transfers. Amounts are kept in cents (int)."""


class InsufficientFunds(Exception):
    pass


class Account:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance
        self.history = []

    def deposit(self, amount):
        self.balance += amount
        self.history.append(("deposit", amount))

    def withdraw(self, amount):
        self.balance -= amount
        self.history.append(("withdraw", amount))


class Bank:
    def __init__(self):
        self.accounts = {}

    def open(self, owner):
        self.accounts[owner] = Account(owner)
        return self.accounts[owner]

    def get(self, owner):
        return self.accounts[owner]

    def transfer(self, src, dst, amount):
        self.get(src).withdraw(amount)
        self.get(dst).deposit(amount)
