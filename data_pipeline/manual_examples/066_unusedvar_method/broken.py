class OrderProcessor:
    def process(self, order):
        subtotal = order.price * order.quantity
        return order.total()
