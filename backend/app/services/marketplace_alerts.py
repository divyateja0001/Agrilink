from __future__ import annotations

from sqlalchemy import select

from ..models import BuyerRequirement, FpoAuthorization, Membership, ProduceLot
from .matching import match_requirement


def active_user_ids_for_organizations(db, organization_ids, roles=None) -> list[str]:
    ids = set(organization_ids)
    if not ids:
        return []
    query = select(Membership.user_id).where(Membership.organization_id.in_(ids), Membership.is_active.is_(True))
    if roles:
        query = query.where(Membership.role.in_(roles))
    return sorted({str(value) for value in db.scalars(query)})


def compatible_supplier_user_ids(db, requirement: BuyerRequirement) -> list[str]:
    farmer_org_ids = {match["lot"].farmer_organization_id for match in match_requirement(db, requirement)}
    user_ids = set(active_user_ids_for_organizations(db, farmer_org_ids, {"farmer"}))
    if farmer_org_ids:
        fpo_ids = set(db.scalars(select(FpoAuthorization.fpo_organization_id).where(
            FpoAuthorization.farmer_organization_id.in_(farmer_org_ids),
            FpoAuthorization.is_active.is_(True),
        )))
        user_ids.update(active_user_ids_for_organizations(db, fpo_ids, {"fpo_manager"}))
    return sorted(user_ids)


def compatible_buyer_user_ids(db, lot: ProduceLot) -> list[str]:
    buyer_org_ids = set()
    requirements = db.scalars(select(BuyerRequirement).where(BuyerRequirement.status.in_(["open", "partially_fulfilled"]))).all()
    for requirement in requirements:
        if any(match["lot"].id == lot.id for match in match_requirement(db, requirement)):
            buyer_org_ids.add(requirement.buyer_organization_id)
    return active_user_ids_for_organizations(db, buyer_org_ids, {"buyer"})
