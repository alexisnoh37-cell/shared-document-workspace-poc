from __future__ import annotations

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from services.errors import AuthenticationError, IntegrationError
from services.identity import normalize_login_identifier

from .common import is_safe_next_url, login_required


bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user:
        return redirect(url_for("documents.index"))
    if request.method == "POST":
        email = normalize_login_identifier(request.form.get("email", ""))
        password = request.form.get("password", "")
        try:
            profile, auth_session, client = current_app.extensions["auth_service"].login(email, password)
        except (AuthenticationError, IntegrationError) as exc:
            flash(str(exc), "danger")
        else:
            session.clear()
            session["auth"] = auth_session
            g.current_user = profile
            g.supabase_client = client
            session.permanent = False
            flash(f"{profile['name']}님, 환영합니다.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if is_safe_next_url(next_url) else url_for("documents.index"))
    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    current_app.extensions["auth_service"].logout(getattr(g, "supabase_client", None))
    session.clear()
    flash("로그아웃했습니다.", "info")
    return redirect(url_for("auth.login"))
