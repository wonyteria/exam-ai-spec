"use client";

import Link from "next/link";

/** Floating glass nav pill — spatial layer above the page. */
export default function Chrome({ title }: { title?: string }) {
  return (
    <Link
      href="/"
      className="glass fixed left-4 top-4 z-40 flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-white/85 transition hover:text-white"
    >
      <span className="bg-gradient-to-br from-indigo-400 to-cyan-300 bg-clip-text text-transparent">
        ◈
      </span>
      시험지 복원
      {title && <span className="font-normal text-white/40">/ {title}</span>}
    </Link>
  );
}
