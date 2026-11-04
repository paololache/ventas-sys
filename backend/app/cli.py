"""CLI: python -m app.cli <comando>"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from .clock import get_clock
from .db import SessionLocal
from .deps import Ctx
from .models import Membership, Tenant, User, Workspace
from .security import hash_password
from .services import excel as xl
from .services.scheduler import run_tick
from .services.seed import seed_workspace


def main(argv=None):
    p = argparse.ArgumentParser(prog="crm")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-superadmin"); a.add_argument("email"); a.add_argument("password")
    a = sub.add_parser("create-tenant"); a.add_argument("name"); a.add_argument("slug"); a.add_argument("owner_email"); a.add_argument("owner_password"); a.add_argument("--workspace", default="Principal")
    a = sub.add_parser("import-excel"); a.add_argument("file"); a.add_argument("--workspace-id", type=int, required=True)
    a = sub.add_parser("quality-report"); a.add_argument("--workspace-id", type=int, required=True)
    sub.add_parser("tick")
    args = p.parse_args(argv)
    with SessionLocal() as db:
        if args.cmd == "create-superadmin":
            db.add(User(email=args.email.lower(), name="Superadmin", password_hash=hash_password(args.password), is_superadmin=True))
            db.commit(); print("OK")
        elif args.cmd == "create-tenant":
            t = Tenant(name=args.name, slug=args.slug, settings={})
            owner = db.scalar(select(User).where(User.email == args.owner_email.lower())) or User(email=args.owner_email.lower(), name="", password_hash=hash_password(args.owner_password))
            db.add_all([t, owner]); db.flush()
            db.add(Membership(user_id=owner.id, tenant_id=t.id, role="owner"))
            ws = Workspace(tenant_id=t.id, name=args.workspace, slug=args.workspace.lower(), settings={})
            db.add(ws); db.flush()
            seed_workspace(db, t, ws, owner.id)
            db.commit(); print(f"tenant={t.id} workspace={ws.id}")
        elif args.cmd in ("import-excel", "quality-report"):
            ws = db.get(Workspace, args.workspace_id)
            t = db.get(Tenant, ws.tenant_id)
            owner = db.scalar(select(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == t.id, Membership.role == "owner"))
            ctx = Ctx(owner, t, ws, "owner")
            today = get_clock().today(t.timezone)
            if args.cmd == "import-excel":
                res = xl.import_excel(db, ctx, args.file, today)
                db.commit()
                print(res)
            print(xl.format_report(xl.quality_report(db, ctx, today)))
        elif args.cmd == "tick":
            print(run_tick(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
