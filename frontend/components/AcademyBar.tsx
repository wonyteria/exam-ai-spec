"use client";

import { useCallback, useEffect, useState } from "react";
import {
  acceptInvite,
  createInvite,
  createTenant,
  devLogin,
  getMe,
  listTenants,
  setActiveTenant,
  switchTenant,
  type Me,
  type Tenant,
} from "@/lib/api";

export default function AcademyBar({ onChanged }: { onChanged?: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [name, setName] = useState("");
  const [newAcademy, setNewAcademy] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [inviteOut, setInviteOut] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const m = await getMe();
      setMe(m);
      if (m.authenticated) {
        const t = await listTenants();
        setTenants(t);
        if (m.tenant_id) setActiveTenant(m.tenant_id);
      }
      onChanged?.();
    } catch (e) {
      setError(String(e));
    }
  }, [onChanged]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const m = await getMe();
        if (cancelled) return;
        setMe(m);
        if (m.authenticated) {
          const t = await listTenants();
          if (!cancelled) setTenants(t);
          if (m.tenant_id) setActiveTenant(m.tenant_id);
        }
        if (!cancelled) onChanged?.();
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onChanged]);

  if (!me?.authenticated) {
    return (
      <div className="w-full max-w-2xl rounded-xl border border-gray-200 bg-white p-4">
        <p className="mb-2 text-sm font-medium">개발 로그인 (dev stub)</p>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-lg border px-3 py-2 text-sm"
            placeholder="사용자 ID"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white"
            onClick={async () => {
              try {
                await devLogin(name);
                setError(null);
                refresh();
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            로그인
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{me.display_name || me.user_id}</span>
        <select
          className="rounded-lg border px-2 py-1.5 text-sm"
          value={me.tenant_id ?? ""}
          onChange={async (e) => {
            try {
              await switchTenant(e.target.value);
              refresh();
            } catch (err) {
              setError(String(err));
            }
          }}
        >
          <option value="">학원 선택…</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.role})
            </option>
          ))}
        </select>
        <input
          className="w-40 rounded-lg border px-2 py-1.5 text-sm"
          placeholder="새 학원 이름"
          value={newAcademy}
          onChange={(e) => setNewAcademy(e.target.value)}
        />
        <button
          className="rounded-lg border px-3 py-1.5 text-sm"
          onClick={async () => {
            try {
              const t = await createTenant(newAcademy);
              await switchTenant(t.id);
              setNewAcademy("");
              refresh();
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          학원 만들기
        </button>
      </div>
      {me.tenant_id && me.role === "owner" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg border px-3 py-1 text-xs"
            onClick={async () => {
              try {
                const inv = await createInvite(me.tenant_id!, "teacher");
                setInviteOut(`teacher: ${inv.code}`);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            교사 초대
          </button>
          <button
            className="rounded-lg border px-3 py-1 text-xs"
            onClick={async () => {
              try {
                const inv = await createInvite(me.tenant_id!, "reviewer");
                setInviteOut(`reviewer: ${inv.code}`);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            검토자 초대
          </button>
          {inviteOut && <code className="text-xs text-gray-600">{inviteOut}</code>}
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <input
          className="w-48 rounded-lg border px-2 py-1 text-xs"
          placeholder="초대 코드"
          value={inviteCode}
          onChange={(e) => setInviteCode(e.target.value)}
        />
        <button
          className="rounded-lg border px-3 py-1 text-xs"
          onClick={async () => {
            try {
              await acceptInvite(inviteCode);
              setInviteCode("");
              refresh();
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          초대 수락
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  );
}
