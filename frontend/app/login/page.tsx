"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { ErrorBox, Field } from "@/components/ui";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await api<{ access_token: string }>("/api/auth/login", { body: { email, password } });
      setToken(r.access_token);
      router.replace("/");
    } catch (ex: any) { setErr(ex.message); }
  }
  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <form onSubmit={submit} className="card space-y-4">
        <div><h1 className="text-xl font-semibold text-brand">CRM comercial proactivo</h1><p className="text-sm text-slate-500">Ingresa con tu cuenta</p></div>
        <ErrorBox msg={err} />
        <Field label="Correo"><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <Field label="Contraseña"><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        <button className="btn btn-primary w-full">Entrar</button>
      </form>
    </main>
  );
}
