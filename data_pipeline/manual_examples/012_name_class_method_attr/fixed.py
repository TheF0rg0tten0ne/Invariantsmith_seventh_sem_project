class InvoiceLine:
    def __init__(self, quantity, unit_price):
        self.quantity = quantity
        self.unit_price = unit_price

    def total(self, discount_rate=1.0):
        return self.quantity * self.unit_price * discount_rate
