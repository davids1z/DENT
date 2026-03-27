"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getAdminUsers, deactivateUser, activateUser, type AdminUser, formatDate } from "@/lib/api";

export default function AdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user || user.role !== "Admin") {
      router.replace("/");
      return;
    }
    loadUsers();
  }, [user, authLoading, router]);

  async function loadUsers() {
    try {
      const data = await getAdminUsers();
      setUsers(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(u: AdminUser) {
    try {
      if (u.isActive) {
        await deactivateUser(u.id);
      } else {
        await activateUser(u.id);
      }
      await loadUsers();
    } catch {
      // ignore
    }
  }

  if (authLoading || !user || user.role !== "Admin") {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-8">
        <h1 className="font-heading text-2xl font-bold">Upravljanje korisnicima</h1>
        <p className="text-sm text-muted mt-1">Pregled i upravljanje korisničkim računima</p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-card animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="border border-border rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-card border-b border-border">
                <th className="text-left px-4 py-3 font-medium text-muted">Korisnik</th>
                <th className="text-left px-4 py-3 font-medium text-muted hidden sm:table-cell">Uloga</th>
                <th className="text-left px-4 py-3 font-medium text-muted hidden md:table-cell">Registriran</th>
                <th className="text-left px-4 py-3 font-medium text-muted hidden md:table-cell">Zadnja prijava</th>
                <th className="text-center px-4 py-3 font-medium text-muted">Analiza</th>
                <th className="text-center px-4 py-3 font-medium text-muted">Status</th>
                <th className="text-right px-4 py-3 font-medium text-muted">Akcija</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border last:border-0 hover:bg-card/50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium">{u.fullName}</div>
                    <div className="text-xs text-muted">{u.email}</div>
                  </td>
                  <td className="px-4 py-3 hidden sm:table-cell">
                    <span className={`inline-flex px-2 py-0.5 rounded-md text-xs font-medium ${
                      u.role === "Admin" ? "bg-purple-50 text-purple-600 border border-purple-200" : "bg-card text-muted border border-border"
                    }`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted hidden md:table-cell">{formatDate(u.createdAt)}</td>
                  <td className="px-4 py-3 text-muted hidden md:table-cell">{u.lastLoginAt ? formatDate(u.lastLoginAt) : "—"}</td>
                  <td className="px-4 py-3 text-center">{u.inspectionCount}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-flex px-2 py-0.5 rounded-md text-xs font-medium ${
                      u.isActive ? "bg-green-50 text-green-600 border border-green-200" : "bg-red-50 text-red-500 border border-red-200"
                    }`}>
                      {u.isActive ? "Aktivan" : "Neaktivan"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {u.role !== "Admin" && (
                      <button
                        onClick={() => handleToggle(u)}
                        className={`text-xs font-medium px-3 py-1.5 rounded-lg transition-colors ${
                          u.isActive
                            ? "text-red-500 hover:bg-red-50"
                            : "text-green-600 hover:bg-green-50"
                        }`}
                      >
                        {u.isActive ? "Deaktiviraj" : "Aktiviraj"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
