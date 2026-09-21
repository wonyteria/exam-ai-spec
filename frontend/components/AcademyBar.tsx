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
      <div className="glass w-full max-w-2xl rounded-2xl p-4">
        <div className="flex gap-2">
          <input
            className="inp flex-1"
            placeholder="사용자 ID"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              devLogin(name)
                .then(() => {
                  setError(null);
                  refresh();
                })
                .catch((err) => setError(String(err)));
            }}
          />
          <button
            className="btn-primary"
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
        {error && <p className="alert-red mt-2 px-3 py-1.5 text-xs">{error}</p>}
      </div>
    );
  }

  return (
    <div className="glass w-full max-w-2xl rounded-2xl p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{me.display_name || me.user_id}</span>
        <select
          className="inp w-auto"
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
          className="inp w-36"
          placeholder="새 학원 이름"
          value={newAcademy}
          onChange={(e) => setNewAcademy(e.target.value)}
        />
        <button
          className="btn-ghost whitespace-nowrap !px-3 !py-1.5 text-xs"
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
            className="btn-ghost !px-3 !py-1 text-xs"
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
            className="btn-ghost !px-3 !py-1 text-xs"
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
          {inviteOut && (
            <code className="glass-soft rounded-lg px-2 py-1 text-xs text-cyan-200">{inviteOut}</code>
          )}
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <input
          className="inp w-44 !py-1 text-xs"
          placeholder="초대 코드"
          value={inviteCode}
          onChange={(e) => setInviteCode(e.target.value)}
        />
        <button
          className="btn-ghost whitespace-nowrap !px-3 !py-1 text-xs"
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
      {error && <p className="alert-red mt-2 px-3 py-1.5 text-xs">{error}</p>}
    </div>
  );
}
