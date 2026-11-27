"""Message formatting and keyboards shared by handlers."""
from __future__ import annotations

import html
from datetime import date, datetime
from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from ..clubs import club_name, is_fit
from ..i18n import LANGS
from ..money import fmt_money, round_k
from ..pricing import Advice, advise
from ..repo import LS, TZ, Repo, today_local
from ..usage import remaining, span, with_bonus
from .callbacks import NOOP, LangCb
from .context import Ctx


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def fmt_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def fmt_day(ctx: Ctx, iso: str) -> str:
    """«7 мая 2027» / «7 май 2027» — plain numbers like 07.05.2027 confuse people."""
    d = date.fromisoformat(iso)
    return f"{d.day} {ctx.t('app.months').split(',')[d.month - 1]} {d.year}"


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def btn(text: str, cb: Any = None, url: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url)
    data = cb.pack() if hasattr(cb, "pack") else cb
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(*rows: list[InlineKeyboardButton] | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def open_app_kb(ctx: Ctx) -> InlineKeyboardMarkup:
    return kb([InlineKeyboardButton(text=ctx.t("app.open_btn"), web_app=WebAppInfo(url=ctx.cfg.webapp_url))])


def main_menu(ctx: Ctx) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    if ctx.cfg.webapp_enabled:
        # With the Mini App on, the chat keeps a single «Open app» button; the old keyboard is taken away.
        return ReplyKeyboardRemove()
    b = lambda key: KeyboardButton(text=ctx.t(key))  # noqa: E731
    return ReplyKeyboardMarkup(
        keyboard=[
            [b("menu.catalog")],
            [b("menu.sell"), b("menu.my")],
            [b("menu.support"), b("menu.how")],
            [b("menu.lang")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def phone_kb(ctx: Ctx) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ctx.t("sell.share_phone"), request_contact=True)],
            [KeyboardButton(text=ctx.t("common.back")), KeyboardButton(text=ctx.t("common.cancel"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def lang_kb(i18n) -> InlineKeyboardMarkup:
    return kb([btn(i18n.t(code, f"lang.{code}"), LangCb(code=code)) for code in LANGS])


def operator_btn(ctx: Ctx) -> InlineKeyboardButton:
    return btn(ctx.t("common.operator_btn"), url=ctx.cfg.support_url)


def noop_btn(text: str) -> InlineKeyboardButton:
    return btn(text, NOOP)


def pager(ctx: Ctx, page: int, pages: int, make_cb) -> list[InlineKeyboardButton] | None:
    if pages <= 1:
        return None
    row = []
    row.append(btn(ctx.t("common.prev"), make_cb(page - 1)) if page > 0 else noop_btn(" "))
    row.append(noop_btn(ctx.t("common.page", page=page + 1, pages=pages)))
    row.append(btn(ctx.t("common.next"), make_cb(page + 1)) if page + 1 < pages else noop_btn(" "))
    return row


def pages_count(total: int, size: int) -> int:
    return max(1, -(-total // size))


def status_label(ctx: Ctx, listing: dict[str, Any]) -> str:
    if listing["status"] == LS.APPROVED and Repo.is_expired(listing):
        return ctx.t("status.expired")
    return ctx.t(f"status.{listing['status']}")


def span_text(ctx: Ctx, days: int) -> str:
    """«10 мес.» / «45 дн.» for a number of days left."""
    r = span(days)
    return f"{r['n']} " + ctx.t(f"app.unit.{r['unit']}")


def left_text(ctx: Ctx, end_iso: str) -> str:
    r = remaining(end_iso, today_local())
    unit = ctx.t(f"app.unit.{r['unit']}")
    return f"{r['n']} {unit}"


def listing_public(ctx: Ctx, data: dict[str, Any], listing_id: int | str = "—") -> str:
    """Public part of a listing: only what a buyer may see. Labels in the viewer's language,
    the seller's own words (tariff, description) as written."""
    promo = data.get("kind") == "promo"
    text = ctx.t(
        "card.body_promo" if promo else "card.body",
        id=listing_id,
        club=esc(club_name(data.get("club"))),
        city=esc(ctx.i18n.city(ctx.lang, data["city"])),
        tariff=esc(data.get("tariff") or ""),
        left=left_text(ctx, data["end_date"]),
        date=fmt_day(ctx, data["end_date"]),
        price=fmt_money(data.get("price") or 0),
    )
    if data.get("price_negotiable"):
        text += ctx.t("card.negotiable")
    if data.get("fee_paid_at"):  # placement paid: Payme or confirmed by an admin
        text += ctx.t("card.verified")
    if not promo and data.get("bonus_days"):
        text += ctx.t("card.bonus", days=data["bonus_days"])
    if data.get("description"):
        text += ctx.t("card.desc", desc=esc(data["description"]))
    return text


def legal_links(ctx: Ctx) -> str:
    """«📄 Offer · User agreement»: the pages the Mini App's server shows; empty without the Mini App."""
    if not ctx.cfg.webapp_enabled:
        return ""
    base = ctx.cfg.webapp_url if ctx.cfg.webapp_url.endswith("/") else ctx.cfg.webapp_url.rsplit("/", 1)[0] + "/"
    return "\n\n" + ctx.t("legal.links", offer=f"{base}offer?lang={ctx.lang}", terms=f"{base}terms?lang={ctx.lang}")


def price_advice(ctx: Ctx, data: dict[str, Any]) -> Advice | None:
    """Price advice for a membership draft (end date from the 1Fit card); None for a promo code or without an end date."""
    if data.get("kind") == "promo" or not data.get("end_date") or not is_fit(data):  # 1Fit's prices: 1Fit only
        return None
    # a draft has the card's end date: the bonus days come after it
    return advise(with_bonus(data["end_date"], data.get("bonus_days")), today_local(), ctx.repo.fit_prices,
                  plan_days=data.get("tariff_days"))


def advice_text(ctx: Ctx, a: Advice) -> str:
    """«Recommended price … ≈ … per month, 1Fit … per month» for the price step."""
    text = ctx.t("advice.block", price=fmt_money(a.recommended), left=span_text(ctx, a.days_left),
                 total=fmt_money(round_k(a.recommended)), fit_total=fmt_money(round_k(a.fit_value)),
                 saving=a.saving(a.recommended))
    return text + ctx.t("advice.own")  # only a suggestion: any price of the seller's goes


def tg_url(username: str | None) -> str | None:
    """https://t.me/name opens the seller's chat for anyone; without a username there is no such link."""
    return f"https://t.me/{username}" if username else None


def contacts_block(ctx: Ctx, name: str, phone: str, username: str | None, user_id: int) -> str:
    """«👤 Сарвар · 📞 +998 90 123 45 67 · ✈️ @name»: what every buyer sees to reach the seller directly."""
    if username:
        tg = f'<a href="{tg_url(username)}">@{esc(username)}</a>'
    else:  # a mention works without a username, unless the seller's privacy settings hide it
        tg = f'<a href="tg://user?id={int(user_id)}">{esc(ctx.t("card.tg_write"))}</a>'
    return ctx.t("card.contacts", name=esc(name), phone=esc(phone or "—"), tg=tg)


async def seller_contacts(ctx: Ctx, listing: dict[str, Any]) -> tuple[str, list[InlineKeyboardButton] | None]:
    """The contacts block and a «Write in Telegram» button for a listing, with today's username of the seller."""
    seller = await ctx.repo.get_user(listing["seller_id"]) or {}
    username = seller.get("username")
    text = contacts_block(ctx, listing["seller_name"], listing["seller_phone"], username, listing["seller_id"])
    url = tg_url(username)
    return text, [btn(ctx.t("card.tg_btn"), url=url)] if url else None


def tg_ref(user: dict[str, Any] | None, user_id: int) -> str:
    if user and user.get("username"):
        return f"{user_id} (@{esc(user['username'])})"
    return str(user_id)
