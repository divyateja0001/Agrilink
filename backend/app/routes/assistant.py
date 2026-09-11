from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select

from ..db import get_session
from ..models import AssistantConversation, AssistantMessage, BuyerRequirement, FpoAuthorization, Order, Organization, ProduceLot, Quotation, QuoteRevision
from ..security import require_roles
from ..serializers import lot_json, org_json, requirement_json
from ..services.matching import available_quantity, match_requirement
from ..services.procurement_assistant import AssistantUnavailable, generate_procurement_advice


bp = Blueprint("assistant", __name__, url_prefix="/api/assistant")
ALLOWED_MODES = {"analyze", "draft_requirement", "draft_counter"}


@bp.post("/procurement")
@require_roles("buyer")
def procurement():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "analyze"))
    message = str(data.get("message", "")).strip()
    if mode not in ALLOWED_MODES or not message or len(message) > 1000:
        return jsonify(error="validation_error", message="Choose a valid assistant mode and enter 1 to 1,000 characters."), 422

    db = get_session()
    context = {"buyer_organization_ids": [str(x) for x in g.principal.organization_ids]}
    source_record_ids = []

    requirement = None
    if requirement_id := data.get("requirement_id"):
        requirement = db.get(BuyerRequirement, requirement_id)
        if not requirement or requirement.buyer_organization_id not in g.principal.organization_ids:
            return jsonify(error="not_found", message="Requirement not found."), 404
        context["requirement"] = requirement_json(requirement)
        source_record_ids.append(str(requirement.id))
        matches = []
        for match in match_requirement(db, requirement)[:10]:
            supplier = db.get(Organization, match["lot"].farmer_organization_id)
            matches.append(
                {
                    "supplier": org_json(supplier),
                    "available_quantity_kg": float(match["available_kg"]),
                    "asking_price_inr_per_kg": match["lot"].asking_price_paise / 100,
                    "quality_grade": match["lot"].quality_grade,
                    "score": match["score"],
                    "explanations": match["explanations"],
                }
            )
        context["deterministic_matches"] = matches

    if quote_id := data.get("quotation_id"):
        quote = db.get(Quotation, quote_id)
        if not quote:
            return jsonify(error="not_found", message="Negotiation not found."), 404
        quote_requirement = db.get(BuyerRequirement, quote.requirement_id)
        if quote_requirement.buyer_organization_id not in g.principal.organization_ids:
            return jsonify(error="not_found", message="Negotiation not found."), 404
        if requirement and requirement.id != quote_requirement.id:
            return jsonify(error="validation_error", message="The requirement and negotiation do not match."), 422
        revision = db.scalar(
            select(QuoteRevision).where(
                QuoteRevision.quotation_id == quote.id,
                QuoteRevision.revision_number == quote.current_revision_number,
            )
        )
        supplier = db.get(Organization, quote.supplier_organization_id)
        context["negotiation"] = {
            "id": str(quote.id),
            "status": quote.status,
            "supplier": org_json(supplier),
            "latest_offer": {
                "quantity_kg": float(revision.offered_quantity_kg),
                "price_inr_per_kg": revision.price_paise_per_kg / 100,
                "quality_grade": revision.quality_grade,
                "delivery_date": revision.delivery_date.isoformat(),
                "delivery_terms": revision.delivery_terms,
                "note": revision.note,
            },
        }
        context.setdefault("requirement", requirement_json(quote_requirement))
        source_record_ids.extend([str(quote_requirement.id), str(quote.id)])

    if mode in {"analyze", "draft_counter"} and not context.get("requirement"):
        return jsonify(error="validation_error", message="Select a requirement or negotiation for this assistant mode."), 422
    if mode == "draft_counter" and not context.get("negotiation"):
        return jsonify(error="validation_error", message="Select a negotiation to draft a counteroffer."), 422

    try:
        result = generate_procurement_advice(
            config=current_app.config,
            mode=mode,
            message=message,
            context=context,
        )
    except AssistantUnavailable as exc:
        fallback = rule_based_response("buyer", mode, message, context)
        result = {
            "answer": fallback["answer"],
            "suggestions": fallback["suggestions"],
            "warnings": [],
            "follow_up_questions": fallback["follow_up_questions"],
            "draft": None,
            "request_id": "fallback",
            "model": "deterministic-rules",
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "advisory": True,
            "source": "rule_based",
            "degraded_reason": exc.code,
        }
    result["source_record_ids"] = sorted(set(source_record_ids))
    return jsonify(result)


SUPPORTED_LANGUAGES = {"en", "te", "hi", "ta"}
ROLE_MODES = {
    "buyer": {"general", "draft_requirement", "analyze", "draft_counter", "crop_guidance"},
    "farmer": {"general", "draft_listing", "find_demand", "draft_quote", "crop_guidance"},
    "fpo_manager": {"general", "draft_listing", "find_demand", "draft_quote", "plan_allocation", "crop_guidance"},
}


def assistant_role():
    roles = g.principal.roles
    return "buyer" if "buyer" in roles else "fpo_manager" if "fpo_manager" in roles else "farmer" if "farmer" in roles else None


def conversation_json(item):
    return {"id": str(item.id), "title": item.title, "role": item.role_context, "language": item.language, "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}


def message_json(item):
    return {"id": str(item.id), "role": item.sender_role, "content": item.content, "source": item.source, "model": item.model, "status": item.status, "metadata": item.metadata_json or {}, "created_at": item.created_at.isoformat()}


def owned_conversation(db, conversation_id):
    return db.scalar(select(AssistantConversation).where(AssistantConversation.id == conversation_id, AssistantConversation.user_id == g.principal.user.id, AssistantConversation.archived_at.is_(None)))


def role_context(db, role):
    context = {"role": role, "organization_ids": [str(value) for value in g.principal.organization_ids]}
    if role == "buyer":
        requirements = db.scalars(select(BuyerRequirement).where(BuyerRequirement.buyer_organization_id.in_(g.principal.organization_ids)).order_by(BuyerRequirement.updated_at.desc()).limit(10)).all()
        context["requirements"] = [requirement_json(item) for item in requirements]
        context["order_count"] = len(db.scalars(select(Order.id).where(Order.buyer_organization_id.in_(g.principal.organization_ids)).limit(101)).all())
        lots = db.scalars(select(ProduceLot).where(ProduceLot.status == "active").order_by(ProduceLot.updated_at.desc()).limit(20)).all()
        supply = []
        for item in lots:
            available = available_quantity(db, item.id)
            if available > 0:
                supply.append({"supplier": org_json(db.get(Organization, item.farmer_organization_id)), "listing": lot_json(item, available)})
        context["available_supply"] = supply
    else:
        farm_ids = set(g.principal.organization_ids)
        if role == "fpo_manager":
            fpo_ids = [item.organization_id for item in g.principal.memberships if item.role == "fpo_manager"]
            farm_ids.update(db.scalars(select(FpoAuthorization.farmer_organization_id).where(FpoAuthorization.fpo_organization_id.in_(fpo_ids), FpoAuthorization.is_active.is_(True))))
        lots = db.scalars(select(ProduceLot).where(ProduceLot.farmer_organization_id.in_(farm_ids), ProduceLot.status == "active").order_by(ProduceLot.updated_at.desc()).limit(20)).all()
        context["authorized_supply"] = [lot_json(item) for item in lots]
        demands = db.scalars(select(BuyerRequirement).where(BuyerRequirement.status.in_(["open", "partially_fulfilled"])).order_by(BuyerRequirement.delivery_deadline).limit(20)).all()
        context["open_buyer_demand"] = [requirement_json(item) for item in demands]
    return context


def rule_based_response(role, mode, message, context):
    """Return a useful, authorized answer when the optional provider is offline."""
    question = " ".join(message.lower().split())
    if mode == "crop_guidance" or any(word in question for word in ("crop recommend", "what crop", "grow", "soil", "irrigation", "season")):
        return {
            "answer": "To suggest suitable crops safely, please share your location, soil type, land area, water availability, planned season, and farming objective. Local soil testing and agricultural advice should confirm any final choice.",
            "suggestions": ["Share the district and season.", "Add soil type and water availability."],
            "follow_up_questions": ["Where is the farm?", "What soil and irrigation are available?"],
        }

    faq = [
        (("what is agrilink", "about agrilink", "platform"), "AgriLink is a B2B agricultural marketplace connecting farmers and FPOs with wholesalers, retailers, restaurants, processors, and institutional buyers. It supports produce listings, buyer requirements, deterministic matching, RFQs, negotiation, order confirmation, stock reservation, dispatch, partial receipt, payment status, reviews, and notifications."),
        (("workflow", "how does it work", "process"), "The AgriLink workflow is: farmer lists produce → buyer posts a requirement → compatible suppliers are ranked → suppliers quote → both sides negotiate → the buyer confirms agreed quotations → stock is reserved atomically → suppliers dispatch → the buyer records partial or complete receipts → payment status and reviews are recorded separately."),
        (("rfq", "request for quotation"), "RFQ means Request for Quotation. A buyer describes the crop, quantity, quality, destination, delivery mode, deadline, and optional budget; compatible farmers or an authorized FPO can then submit price and quantity offers."),
        (("negotiat", "counteroffer", "counter offer"), "Negotiation keeps every offer revision and participant message in order. Buyer and supplier can counter price, quantity, delivery date, mode, charges, and terms. Stock is not reserved until the buyer confirms accepted terms."),
        (("matching", "match supplier", "score"), "Supplier matching is deterministic, not trained AI. It first filters crop, acceptable quality, availability, and delivery compatibility, then ranks quantity coverage, price fit, and delivery fit with explanations. Multiple suppliers can cover one requirement."),
        (("fpo", "farmer producer organization"), "An FPO can coordinate only explicitly authorized member farmers, combine their available supply, preserve each farmer's contribution, and help quote or dispatch. It cannot access unrelated farms."),
        (("stock", "reservation", "oversell", "inventory"), "Available stock equals on-hand stock minus active reservations. Order confirmation and reservation happen in one database transaction with locking, duplicate confirmation is idempotent, dispatch reduces on-hand stock and its reservation, and cancellation releases only unshipped stock."),
        (("partial", "receipt", "received quantity"), "AgriLink supports partial dispatches and partial receipts. A receipt cannot exceed dispatched quantity, duplicate receipt requests do not count twice, and the remaining quantity stays outstanding until later delivery."),
        (("payment", "razorpay"), "Payments are separate from fulfillment. The prototype supports clearly labelled simulated records and optional Razorpay test-mode checkout; neither represents a live transfer. Provider events are signature-checked and duplicate effects are prevented."),
        (("review", "rating", "feedback"), "A buyer can review a supplier or coordinating FPO only after the complete order is received. Ratings cover overall experience, quality, delivery, and communication, with one review per order and supplier target."),
        (("notification", "alert"), "Marketplace events are written to a transactional outbox and delivered as in-app notifications to relevant users. The worker retries temporary failures without duplicate notification effects; browser push is optional."),
        (("track", "gps", "vehicle", "driver", "arrival"), "Each dispatch has its own assigned driver and vehicle tracking record. Real GPS starts only after driver permission and Start Delivery; simulated tracking is visibly labelled. Buyers see the last recorded position and stale state. Driver arrival never confirms buyer receipt."),
        (("delivery mode", "pickup", "seller delivery"), "Produce and requirements record delivery mode. Buyer Pickup means the buyer arranges collection; Delivery Available or Delivery Required means seller delivery terms, service location, date, radius, and charges can be checked during matching and negotiation."),
        (("secure", "security", "permission", "private"), "AgriLink uses hashed passwords, expiring server sessions, CSRF protection, backend role and organization checks, rate limits, validation, audit history, and private order access. A driver can access only assigned dispatches and gains no farmer or buyer permissions."),
        (("what can you do", "help me", "your features"), "I can explain AgriLink, summarize authorized marketplace records, help buyers draft requirements and counteroffers, help farmers draft listings and quotations, explain matching and fulfillment, and give cautious general crop-planning guidance. I cannot reserve stock, confirm orders, submit offers, or record payments."),
    ]
    for phrases, answer in faq:
        if any(phrase in question for phrase in phrases):
            return {"answer": answer, "suggestions": ["Ask a follow-up question for a step-by-step explanation."], "follow_up_questions": []}

    if role == "buyer":
        matches = context.get("deterministic_matches") or []
        if matches:
            lines = [
                f"{item['supplier']['name']}: {item['available_quantity_kg']:g} kg at ₹{item['asking_price_inr_per_kg']:g}/kg (match score {item['score']:g})."
                for item in matches[:5]
            ]
            return {
                "answer": f"I found {len(matches)} compatible supplier listing{'s' if len(matches) != 1 else ''} for the selected requirement:\n\n" + "\n".join(f"- {line}" for line in lines),
                "suggestions": ["Compare delivery terms before sending an RFQ.", "Use Negotiations to agree price and quantity."],
                "follow_up_questions": [],
            }
        supply = context.get("available_supply") or []
        if supply and any(word in question for word in ("supplier", "available", "supply", "produce", "listing", "price")):
            lines = []
            for item in supply[:6]:
                lot = item["listing"]
                delivery = "delivery available" if lot["delivery_mode"] == "seller_delivery" else "buyer pickup"
                lines.append(f"{item['supplier']['name']}: {lot['available_quantity_kg']:g} kg {lot['crop']} ({lot['variety']}, grade {lot['quality_grade']}) at ₹{lot['asking_price_inr']:g}/kg, {lot['location']}; {delivery}.")
            return {
                "answer": f"I found {len(supply)} active supplier listing{'s' if len(supply) != 1 else ''} in AgriLink. Here are the first {len(lines)}:\n\n" + "\n".join(f"- {line}" for line in lines),
                "suggestions": ["Post a requirement to rank these suppliers for quantity, price, and delivery fit."],
                "follow_up_questions": ["Which crop, quantity, destination, and delivery date do you need?"],
            }
        return {"answer": "There are no active supplier listings available right now.", "suggestions": ["Post a requirement so matching can alert compatible suppliers."], "follow_up_questions": []}

    demands = context.get("open_buyer_demand") or []
    if demands and any(word in question for word in ("demand", "requirement", "buyer", "available", "quote")):
        lines = [f"{item['quantity_kg']:g} kg {item['crop']} ({item['acceptable_quality']}) to {item['destination']} by {item['delivery_deadline']}." for item in demands[:6]]
        return {
            "answer": f"I found {len(demands)} open buyer requirement{'s' if len(demands) != 1 else ''}. Here are the first {len(lines)}:\n\n" + "\n".join(f"- {line}" for line in lines),
            "suggestions": ["Open Buyer demand to check listing compatibility before quoting."],
            "follow_up_questions": [],
        }
    return {"answer": "I can answer questions about AgriLink workflows, RFQs, negotiation, matching, FPO coordination, inventory, delivery tracking, payments, reviews, notifications, and general crop planning. Please ask about one of these areas.", "suggestions": ["Ask: How does stock reservation prevent overselling?", "Ask: How does vehicle tracking protect driver privacy?"], "follow_up_questions": ["Which AgriLink feature would you like explained?"]}


def add_selected_context(db, context, data, role):
    if requirement_id := data.get("requirement_id"):
        requirement = db.get(BuyerRequirement, requirement_id)
        if not requirement:
            return None
        if role == "buyer" and requirement.buyer_organization_id not in g.principal.organization_ids:
            return None
        context["selected_requirement"] = requirement_json(requirement)
        if role == "buyer":
            context["deterministic_matches"] = [
                {
                    "supplier": org_json(db.get(Organization, match["lot"].farmer_organization_id)),
                    "available_quantity_kg": float(match["available_kg"]),
                    "asking_price_inr_per_kg": match["lot"].asking_price_paise / 100,
                    "score": match["score"],
                    "explanations": match["explanations"],
                }
                for match in match_requirement(db, requirement)[:10]
            ]
    if quote_id := data.get("quotation_id"):
        quote = db.get(Quotation, quote_id)
        requirement = db.get(BuyerRequirement, quote.requirement_id) if quote else None
        if not quote or not requirement:
            return None
        permitted = (
            requirement.buyer_organization_id in g.principal.organization_ids
            or quote.supplier_organization_id in g.principal.organization_ids
            or (quote.coordinating_fpo_id and quote.coordinating_fpo_id in g.principal.organization_ids)
        )
        if not permitted:
            return None
        revision = db.scalar(select(QuoteRevision).where(QuoteRevision.quotation_id == quote.id, QuoteRevision.revision_number == quote.current_revision_number))
        context["selected_requirement"] = requirement_json(requirement)
        context["selected_negotiation"] = {
            "id": str(quote.id),
            "status": quote.status,
            "supplier": org_json(db.get(Organization, quote.supplier_organization_id)),
            "latest_offer": {
                "quantity_kg": float(revision.offered_quantity_kg),
                "price_inr_per_kg": revision.price_paise_per_kg / 100,
                "quality_grade": revision.quality_grade,
                "delivery_date": revision.delivery_date.isoformat(),
                "delivery_terms": revision.delivery_terms,
            },
        }
    return context


@bp.get("/conversations")
@require_roles("buyer", "farmer", "fpo_manager")
def list_conversations():
    db = get_session(); role = assistant_role()
    rows = db.scalars(select(AssistantConversation).where(AssistantConversation.user_id == g.principal.user.id, AssistantConversation.archived_at.is_(None)).order_by(AssistantConversation.updated_at.desc()).limit(30)).all()
    return jsonify(role=role, items=[conversation_json(item) for item in rows])


@bp.post("/conversations")
@require_roles("buyer", "farmer", "fpo_manager")
def create_conversation():
    data = request.get_json(silent=True) or {}; role = assistant_role(); language = str(data.get("language", g.principal.user.locale or "en"))
    if language not in SUPPORTED_LANGUAGES: language = "en"
    item = AssistantConversation(user_id=g.principal.user.id, title="New conversation", role_context=role, language=language)
    db = get_session(); db.add(item); db.commit(); return jsonify(conversation_json(item)), 201


@bp.get("/conversations/<uuid:conversation_id>/messages")
@require_roles("buyer", "farmer", "fpo_manager")
def conversation_messages(conversation_id):
    db = get_session(); conversation = owned_conversation(db, conversation_id)
    if not conversation: return jsonify(error="not_found", message="Conversation not found."), 404
    rows = db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.created_at)).all()
    return jsonify(conversation=conversation_json(conversation), items=[message_json(item) for item in rows])


@bp.post("/conversations/<uuid:conversation_id>/messages")
@require_roles("buyer", "farmer", "fpo_manager")
def send_conversation_message(conversation_id):
    db = get_session(); conversation = owned_conversation(db, conversation_id); data = request.get_json(silent=True) or {}
    if not conversation: return jsonify(error="not_found", message="Conversation not found."), 404
    message = str(data.get("message", "")).strip(); mode = str(data.get("mode", "general")); language = str(data.get("language", conversation.language))
    if not message or len(message) > 1000 or mode not in ROLE_MODES[conversation.role_context] or language not in SUPPORTED_LANGUAGES:
        return jsonify(error="validation_error", message="Enter 1 to 1,000 characters and choose an available assistant task."), 422
    history_rows = db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id).order_by(AssistantMessage.created_at.desc()).limit(12)).all()
    history = [{"role": item.sender_role, "content": item.content} for item in reversed(history_rows)]
    context = add_selected_context(db, role_context(db, conversation.role_context), data, conversation.role_context)
    if context is None:
        return jsonify(error="not_found", message="The selected marketplace context is not available to this account."), 404
    user_message = AssistantMessage(conversation_id=conversation.id, sender_role="user", content=message, source="user", status="completed")
    db.add(user_message); db.flush()
    if conversation.title == "New conversation": conversation.title = message[:117] + ("..." if len(message) > 117 else "")
    conversation.language = language
    try:
        result = generate_procurement_advice(config=current_app.config, mode=mode, message=message, context=context, history=history, role=conversation.role_context, language=language)
    except AssistantUnavailable as exc:
        fallback = rule_based_response(conversation.role_context, mode, message, context)
        result = {"answer": fallback["answer"], "suggestions": fallback["suggestions"], "warnings": [], "follow_up_questions": fallback["follow_up_questions"], "draft": None, "source": "rule_based", "degraded_reason": exc.code, "request_id": "fallback", "model": "deterministic-rules", "generated_at": datetime.now(timezone.utc).isoformat(), "advisory": True, "token_count": None}
    assistant_message = AssistantMessage(conversation_id=conversation.id, sender_role="assistant", content=result["answer"], source=result["source"], model=result["model"], status="completed", token_count=result.get("token_count"), metadata_json={key: result.get(key) for key in ("suggestions", "warnings", "follow_up_questions", "draft", "degraded_reason", "request_id", "advisory")})
    db.add(assistant_message); db.commit()
    return jsonify(conversation=conversation_json(conversation), message=message_json(assistant_message), result=result), 201


@bp.post("/conversations/<uuid:conversation_id>/reset")
@require_roles("buyer", "farmer", "fpo_manager")
def reset_conversation(conversation_id):
    db = get_session(); conversation = owned_conversation(db, conversation_id)
    if not conversation: return jsonify(error="not_found", message="Conversation not found."), 404
    conversation.archived_at = datetime.now(timezone.utc)
    replacement = AssistantConversation(user_id=g.principal.user.id, title="New conversation", role_context=conversation.role_context, language=conversation.language)
    db.add(replacement); db.commit(); return jsonify(conversation_json(replacement)), 201
