"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, token, Me } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    api<Me>("/api/auth/me").then((me) => {
      const ws = me.tenants.flatMap((t) => t.workspaces)[0];
      router.replace(ws ? `/w/${ws.id}` : me.is_superadmin ? "/admin" : "/login");
    }).catch(() => router.replace("/login"));
  }, [router]);
  return <p className="p-8 text-slate-500">Cargando…</p>;
}
