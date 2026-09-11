from datetime import date, timedelta
from decimal import Decimal

from app.db import session_scope
from app.models import BuyerRequirement, Organization, ProduceLot, User
from app.services.matching import allocation_preview


def test_partial_supplier_allocation_and_shortfall(app):
    with app.app_context(), session_scope(app) as db:
        buyer = Organization(name="Test buyer", org_type="buyer", location="X")
        farm = Organization(name="Test farm", org_type="farm", location="Y")
        user = User(email="test@example.com", full_name="Test", password_hash="not-used")
        db.add_all([buyer, farm, user]); db.flush()
        lot = ProduceLot(farmer_organization_id=farm.id, created_by_user_id=user.id, crop="Tomato", variety="V1", quality_grade="A", quantity_on_hand_kg=Decimal("400"), asking_price_paise=2000, location="Y", delivery_mode="buyer_pickup", harvest_date=date.today(), available_from=date.today(), available_until=date.today()+timedelta(days=10))
        req = BuyerRequirement(buyer_organization_id=buyer.id, created_by_user_id=user.id, crop="Tomato", variety="V1", quantity_kg=Decimal("1000"), acceptable_quality="B", destination="X", delivery_mode="buyer_pickup", delivery_deadline=date.today()+timedelta(days=5), budget_price_paise=2500)
        db.add_all([lot, req]); db.flush()
        allocations, shortfall = allocation_preview(db, req)
        assert allocations[0]["suggested_quantity_kg"] == Decimal("400")
        assert shortfall == Decimal("600")
