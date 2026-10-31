from decimal import Decimal

rates = [Decimal("0.30"), Decimal("-0.20")]
cumulative_return = Decimal("1")

for rate in rates:
    cumulative_return *= Decimal("1") + rate

cumulative_return -= Decimal("1")
print(f"Cumulative return: {cumulative_return:.2%}")
