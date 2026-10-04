class InvoiceLine:
    def __init__(self, quantity, unit_price):
        self.quantity = quantity
        self.unit_price = unit_price

    def total(self):
        return self.quantity * self.unit_price * discount_rate
